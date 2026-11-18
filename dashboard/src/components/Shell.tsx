import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  IconChevronDown, IconDevice, IconHome, IconLogout, IconMenu, IconParticipation, IconReports, IconResults,
  IconSettings, IconUser, LogoMark,
} from "./Icons";

export interface NavItem { path: string; label: string; icon: (p: { size?: number }) => JSX.Element }
export const NAV: NavItem[] = [
  { path: "/", label: "Inicio", icon: IconHome },
  { path: "/resultados", label: "Resultados", icon: IconResults },
  { path: "/participacion", label: "Participación", icon: IconParticipation },
  { path: "/dispositivo", label: "Dispositivo", icon: IconDevice },
  { path: "/reportes", label: "Reportes", icon: IconReports },
  { path: "/configuracion", label: "Configuración", icon: IconSettings },
];

export function Shell({ title, route, onLogout, children }: { title: string; route: string; onLogout: () => void; children: ReactNode }) {
  const [menu, setMenu] = useState(false);
  const [drawer, setDrawer] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => { setDrawer(false); }, [route]);
  useEffect(() => {
    if (!menu) return;
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !menuRef.current?.contains(e.target as Node)) setMenu(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", close); };
  }, [menu]);

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <button className="icon-btn" aria-label="Abrir navegación" aria-expanded={drawer} onClick={() => setDrawer((v) => !v)}>
            <IconMenu />
          </button>
          <LogoMark />
          <span>{title}</span>
        </div>
        <div className="topbar-actions" ref={menuRef}>
          <button className="user-btn" aria-haspopup="menu" aria-expanded={menu} onClick={() => setMenu((v) => !v)}>
            <span className="avatar-ring"><IconUser size={13} /></span>
            Administrador
            <IconChevronDown size={13} />
          </button>
          {menu && (
            <div className="menu" role="menu">
              <button role="menuitem" onClick={onLogout}><IconLogout size={16} /> Cerrar sesión</button>
            </div>
          )}
        </div>
      </header>
      <div className="body">
        <nav className={`sidebar${drawer ? " open" : ""}`} aria-label="Navegación principal">
          {NAV.map(({ path, label, icon: Icon }) => (
            <a key={path} className="nav-link" href={`#${path}`} aria-current={route === path ? "page" : undefined}>
              <Icon size={17} />{label}
            </a>
          ))}
        </nav>
        <main className="content">{children}</main>
      </div>
    </div>
  );
}
