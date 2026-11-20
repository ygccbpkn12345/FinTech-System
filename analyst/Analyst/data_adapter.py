"""
数据适配器 - 自动发现可用股票
"""
import os
import pandas as pd
from pathlib import Path
import yaml


class DataAdapter:
    """数据适配器基类"""
    
    def fetch(self, stock_code, start_date=None, end_date=None):
        raise NotImplementedError
    
    def get_all_stocks(self):
        """获取该数据源能提供的所有股票代码"""
        raise NotImplementedError
    
    def is_available(self):
        return True


class LocalFileAdapter(DataAdapter):
    """本地文件适配器 - 自动扫描目录"""
    
    def __init__(self, data_dir="data/technical_indicators/"):
        self.data_dir = Path(data_dir)
    
    def fetch(self, stock_code, start_date=None, end_date=None):
        file_path = self.data_dir / f"{stock_code}.csv"
        if not file_path.exists():
            raise FileNotFoundError(f"数据文件不存在: {file_path}")
        df = pd.read_csv(file_path)
        if 'date' not in df.columns:
            raise ValueError(f"缺少 date 列: {file_path}")
        df['date'] = pd.to_datetime(df['date'])
        return df
    
    def get_all_stocks(self):
        """扫描目录，自动发现所有 CSV 文件"""
        if not self.data_dir.exists():
            return []
        return [f.stem for f in self.data_dir.glob("*.csv")]
    
    def is_available(self):
        return self.data_dir.exists()


class AkshareAdapter(DataAdapter):
    """AKShare 适配器 - 实时查询"""
    
    def fetch(self, stock_code, start_date=None, end_date=None):
        try:
            import akshare as ak
        except ImportError:
            raise ImportError("请安装 akshare: pip install akshare")
        
        start = start_date.replace('-', '') if start_date else "20220101"
        end = end_date.replace('-', '') if end_date else "20250101"
        
        df = ak.stock_zh_a_hist(
            symbol=stock_code,
            period="daily",
            start_date=start,
            end_date=end,
            adjust="qfq"
        )
        
        if df is None or df.empty:
            raise ValueError(f"未获取到 {stock_code} 的数据")
        
        df = df.rename(columns={'日期': 'date', '收盘': 'close'})
        df['date'] = pd.to_datetime(df['date'])
        return df[['date', 'close']]
    
    def get_all_stocks(self):
        """获取所有 A 股股票代码"""
        try:
            import akshare as ak
            # 获取所有 A 股代码
            df = ak.stock_info_a_code_name()
            return df['code'].tolist()
        except Exception as e:
            print(f"获取 A 股列表失败: {e}")
            return []
    
    def is_available(self):
        try:
            import akshare
            return True
        except ImportError:
            return False


class TushareAdapter(DataAdapter):
    """Tushare 适配器 - API 调用"""
    
    def __init__(self, token=None):
        self.token = token
        self._pro = None
    
    def _init_pro(self):
        if self._pro is None and self.token:
            try:
                import tushare as ts
                ts.set_token(self.token)
                self._pro = ts.pro_api()
            except ImportError:
                pass
    
    def fetch(self, stock_code, start_date=None, end_date=None):
        if not self.token:
            raise ValueError("Tushare 需要 token")
        self._init_pro()
        if self._pro is None:
            raise ImportError("tushare 未安装或 token 无效")
        
        start = start_date.replace('-', '') if start_date else "20220101"
        end = end_date.replace('-', '') if end_date else "20250101"
        
        df = self._pro.daily(ts_code=f"{stock_code}.SZ", start_date=start, end_date=end)
        
        if df is None or df.empty:
            df = self._pro.daily(ts_code=f"{stock_code}.SZ", start_date=start, end_date=end)
        
        if df is None or df.empty:
            raise ValueError(f"未获取到 {stock_code} 的数据")
        
        df = df.rename(columns={'trade_date': 'date', 'close': 'close'})
        df['date'] = pd.to_datetime(df['date'])
        return df[['date', 'close']]
    
    def get_all_stocks(self):
        """获取所有 A 股股票代码"""
        self._init_pro()
        if self._pro is None:
            return []
        
        try:
            # 获取沪深 A 股列表
            df = self._pro.stock_basic(exchange='', list_status='L')
            return df['ts_code'].str.replace('.SZ', '').str.replace('.SH', '').tolist()
        except Exception as e:
            print(f"获取 A 股列表失败: {e}")
            return []
    
    def is_available(self):
        return bool(self.token)


class DataFetcher:
    """自动发现股票的获取器"""
    
    def __init__(self, config_path="data_config.yaml"):
        self.config_path = config_path
        self.config = self._load_config()
        self.adapters = self._create_adapters()
        self._stock_cache = None
    
    def _load_config(self):
        if Path(self.config_path).exists():
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        return {
            "data_sources": [
                {"type": "local_file", "priority": 1, "data_dir": "data/technical_indicators/"}
            ]
        }
    
    def _create_adapters(self):
        sources = self.config.get('data_sources', [])
        sources = sorted(sources, key=lambda x: x.get('priority', 999))
        
        adapters = []
        for source in sources:
            source_type = source.get('type')
            if source_type == 'local_file':
                adapters.append(LocalFileAdapter(source.get('data_dir', 'data/technical_indicators/')))
            elif source_type == 'akshare':
                adapters.append(AkshareAdapter())
            elif source_type == 'tushare':
                adapters.append(TushareAdapter(os.getenv('TUSHARE_TOKEN') or source.get('token')))
        return adapters
    
    def get_available_stocks(self):
        """获取所有可用的股票（自动去重）"""
        if self._stock_cache is not None:
            return self._stock_cache
        
        all_stocks = set()
        
        for adapter in self.adapters:
            try:
                if not adapter.is_available():
                    continue
                stocks = adapter.get_all_stocks()
                if stocks:
                    all_stocks.update(stocks)
                    print(f"  ✅ {adapter.__class__.__name__}: 发现 {len(stocks)} 只股票")
                else:
                    print(f"  ⚠️ {adapter.__class__.__name__}: 未发现股票")
            except Exception as e:
                print(f"  ❌ {adapter.__class__.__name__}: {e}")
                continue
        
        self._stock_cache = list(all_stocks)
        return self._stock_cache
    
    def fetch(self, stock_code, start_date=None, end_date=None):
        """按优先级尝试所有数据源"""
        if start_date is None:
            start_date = self.config.get('start_date')
        if end_date is None:
            end_date = self.config.get('end_date')
        
        last_error = None
        
        for adapter in self.adapters:
            try:
                if not adapter.is_available():
                    continue
                df = adapter.fetch(stock_code, start_date, end_date)
                print(f"  ✅ 使用 {adapter.__class__.__name__}: {stock_code}")
                return df
            except Exception as e:
                last_error = e
                print(f"  ❌ {adapter.__class__.__name__}: {stock_code} 失败: {e}")
                continue
        
        raise RuntimeError(f"所有数据源均失败: {last_error}")