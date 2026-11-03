import type { ReactNode, SVGProps } from "react";

type P = SVGProps<SVGSVGElement> & { size?: number };
function Svg({ size = 18, children, ...rest }: P & { children: ReactNode }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false" {...rest}>{children}</svg>
  );
}

export const IconHome = (p: P) => <Svg {...p}><path d="M3 11l9-8 9 8" /><path d="M5 10v10h5v-6h4v6h5V10" /></Svg>;
export const IconResults = (p: P) => <Svg {...p}><path d="M4 20V10M10 20V4M16 20v-7M22 20H2" /></Svg>;
export const IconParticipation = (p: P) => <Svg {...p}><path d="M4 20V13M10 20V8M16 20v-5" /><path d="M3 20h18" /><circle cx="19" cy="6" r="2.5" /></Svg>;
export const IconDevice = (p: P) => <Svg {...p}><rect x="3" y="4" width="18" height="12" rx="2" /><path d="M8 20h8M12 16v4" /></Svg>;
export const IconReports = (p: P) => <Svg {...p}><path d="M6 3h8l5 5v13H6z" /><path d="M14 3v5h5M9 17v-3M12 17v-6M15 17v-2" /></Svg>;
export const IconSettings = (p: P) => (
  <Svg {...p}><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 00.3 1.8l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-1.8-.3 1.7 1.7 0 00-1 1.5V21a2 2 0 11-4 0v-.1a1.7 1.7 0 00-1.1-1.5 1.7 1.7 0 00-1.8.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.7 1.7 0 00.3-1.8 1.7 1.7 0 00-1.5-1H3a2 2 0 110-4h.1a1.7 1.7 0 001.5-1.1 1.7 1.7 0 00-.3-1.8l-.1-.1a2 2 0 112.8-2.8l.1.1a1.7 1.7 0 001.8.3H9a1.7 1.7 0 001-1.5V3a2 2 0 114 0v.1a1.7 1.7 0 001 1.5 1.7 1.7 0 001.8-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 00-.3 1.8V9a1.7 1.7 0 001.5 1H21a2 2 0 110 4h-.1a1.7 1.7 0 00-1.5 1z" /></Svg>
);
export const IconUser = (p: P) => <Svg {...p}><circle cx="12" cy="8" r="4" /><path d="M4 21a8 8 0 0116 0" /></Svg>;
export const IconChevronDown = (p: P) => <Svg {...p}><path d="M6 9l6 6 6-6" /></Svg>;
export const IconChevronRight = (p: P) => <Svg {...p}><path d="M9 6l6 6-6 6" /></Svg>;
export const IconCalendar = (p: P) => <Svg {...p}><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M3 10h18M8 3v4M16 3v4" /></Svg>;
export const IconDownload = (p: P) => <Svg {...p}><path d="M12 3v12M7 10l5 5 5-5M4 21h16" /></Svg>;
export const IconMenu = (p: P) => <Svg {...p}><path d="M4 6h16M4 12h16M4 18h16" /></Svg>;
export const IconLogout = (p: P) => <Svg {...p}><path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9" /></Svg>;
export const IconAlert = (p: P) => <Svg {...p}><path d="M12 3l10 18H2z" /><path d="M12 10v5M12 18h.01" /></Svg>;
export const IconRefresh = (p: P) => <Svg {...p}><path d="M20 11a8 8 0 10-2.3 5.7M20 4v7h-7" /></Svg>;

// Componentes del equipo
export const IconBallotBox = (p: P) => <Svg {...p}><rect x="4" y="12" width="16" height="9" rx="1.5" /><path d="M7 12V4h10v8M10 8l1.6 1.6L15 6" /></Svg>;
export const IconCamera = (p: P) => <Svg {...p}><path d="M4 8h3l2-3h6l2 3h3v11H4z" /><circle cx="12" cy="13" r="3.5" /></Svg>;
export const IconRfid = (p: P) => <Svg {...p}><rect x="4" y="3" width="16" height="18" rx="2" /><path d="M9 12.5a3 3 0 013-3M9 16a6.5 6.5 0 016.5-6.5M12 8h.01" /></Svg>;
export const IconDatabase = (p: P) => <Svg {...p}><ellipse cx="12" cy="6" rx="8" ry="3" /><path d="M4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6" /></Svg>;
export const IconWifi = (p: P) => <Svg {...p}><path d="M2 9a15 15 0 0120 0M5 12.5a10.5 10.5 0 0114 0M8.5 16a5.5 5.5 0 017 0" /><path d="M12 19.5h.01" /></Svg>;
export const IconFingerprint = (p: P) => <Svg {...p}><path d="M6 11a6 6 0 0112 0v2.5M9 21c.6-1.4 1-2.7 1-4.5V11a2 2 0 014 0v2c0 3 .5 5 1.5 7M4.5 15c.3-1 .5-2 .5-3.5" /></Svg>;

export const COMPONENT_ICONS: Record<string, (p: P) => JSX.Element> = {
  kiosk: IconBallotBox, camera: IconCamera, nfc: IconRfid, fingerprint: IconFingerprint, database: IconDatabase, network: IconWifi,
};

export function LogoMark({ size = 30 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <rect x="6" y="14" width="20" height="12" rx="2.5" fill="#fff" />
      <rect x="10" y="6" width="12" height="11" rx="1.5" fill="#dbe7fb" stroke="#fff" strokeWidth="1.2" />
      <path d="M13 11.5l2.4 2.4 4.4-4.6" fill="none" stroke="#0b5bd3" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
