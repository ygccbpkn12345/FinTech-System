// 轻量 hash 路由：不引入 react-router 等额外依赖
// 用法：useHashRoute() 返回 { path, query }；<Link to="/backtest?experiment=x"> 渲染 <a href="#/backtest?...">
import { useEffect, useState, type ReactNode, type MouseEvent } from 'react';

export interface HashRoute {
  path: string;   // 如 "/backtest"
  query: URLSearchParams;
  hash: string;   // 完整 hash，如 "#/backtest?experiment=x"
}

function parse(): HashRoute {
  const raw = window.location.hash || '#/';
  const body = raw.replace(/^#/, '');
  const [path, qs = ''] = body.split('?');
  return {
    path: path === '' ? '/' : path.replace(/\/+$/, '') || '/',
    query: new URLSearchParams(qs),
    hash: raw,
  };
}

export function useHashRoute(): HashRoute {
  const [route, setRoute] = useState<HashRoute>(parse);
  useEffect(() => {
    const onChange = () => setRoute(parse());
    window.addEventListener('hashchange', onChange);
    return () => window.removeEventListener('hashchange', onChange);
  }, []);
  return route;
}

export function navigate(to: string) {
  const target = to.startsWith('#') ? to : `#${to.startsWith('/') ? to : `/${to}`}`;
  if (window.location.hash === target) {
    window.dispatchEvent(new HashChangeEvent('hashchange'));
  } else {
    window.location.hash = target;
  }
}

export function Link({
  to, children, className, onClick, ...rest
}: {
  to: string;
  children: ReactNode;
  className?: string;
  onClick?: (e: MouseEvent<HTMLAnchorElement>) => void;
  title?: string;
}) {
  const href = to.startsWith('#') ? to : `#${to.startsWith('/') ? to : `/${to}`}`;
  return (
    <a href={href} className={className} onClick={onClick} {...rest}>
      {children}
    </a>
  );
}
