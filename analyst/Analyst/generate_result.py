"""
生成涨跌幅数据文件 - 自动发现所有可用股票
"""
from pathlib import Path
import pandas as pd
from data_adapter import DataFetcher


def generate_all_results():
    fetcher = DataFetcher("data_config.yaml")
    
    # 自动获取所有可用股票
    print("📊 正在扫描可用股票...")
    print("-" * 50)
    stock_list = fetcher.get_available_stocks()
    print("-" * 50)
    
    if not stock_list:
        print("⚠️ 未发现任何股票，请检查数据源配置")
        return
    
    print(f"✅ 共发现 {len(stock_list)} 只股票")
    
    # 创建 result 目录
    result_dir = Path("result")
    result_dir.mkdir(parents=True, exist_ok=True)
    
    # 处理每一只股票
    success_count = 0
    fail_count = 0
    
    for stock_code in stock_list:
        try:
            print(f"\n📈 处理 {stock_code}...")
            df = fetcher.fetch(stock_code)
            
            if "date" not in df.columns or "close" not in df.columns:
                print(f"⚠️ 跳过 {stock_code}: 缺少 date 或 close 列")
                fail_count += 1
                continue
            
            close = pd.to_numeric(df["close"], errors="coerce")
            result = pd.DataFrame({
                "date": df["date"],
                "pct_change": close.pct_change() * 100,
            }).dropna()
            
            if len(result) == 0:
                print(f"⚠️ 跳过 {stock_code}: 数据为空")
                fail_count += 1
                continue
            
            output_file = result_dir / f"{stock_code}.csv"
            result.to_csv(output_file, index=False)
            print(f"✅ 已生成: {output_file}, 共 {len(result)} 条记录")
            success_count += 1
            
        except Exception as e:
            print(f"❌ 处理 {stock_code} 失败: {e}")
            fail_count += 1
    
    print("\n" + "=" * 50)
    print(f"✅ 成功: {success_count} 只")
    print(f"❌ 失败: {fail_count} 只")
    print("=" * 50)
    print("🎉 处理完成!")


if __name__ == "__main__":
    generate_all_results()