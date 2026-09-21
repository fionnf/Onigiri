type Props = { className?: string };

const base = "h-4 w-4 shrink-0";

function Svg({ children, className }: Props & { children: React.ReactNode }) {
  return (
    <svg
      className={className ?? base}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  );
}

export const IconSearch = (p: Props) => (
  <Svg {...p}>
    <circle cx="11" cy="11" r="7" />
    <path d="m20 20-3.5-3.5" />
  </Svg>
);
export const IconPlus = (p: Props) => (
  <Svg {...p}>
    <path d="M12 5v14M5 12h14" />
  </Svg>
);
export const IconBook = (p: Props) => (
  <Svg {...p}>
    <path d="M4 5a2 2 0 0 1 2-2h13v18H6a2 2 0 0 1-2-2z" />
    <path d="M8 3v18" />
  </Svg>
);
export const IconUser = (p: Props) => (
  <Svg {...p}>
    <circle cx="12" cy="8" r="4" />
    <path d="M5 21a7 7 0 0 1 14 0" />
  </Svg>
);
export const IconSettings = (p: Props) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="3" />
    <path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.2 2.2M16.9 16.9l2.2 2.2M19.1 4.9l-2.2 2.2M7.1 16.9l-2.2 2.2" />
  </Svg>
);
export const IconStar = ({ filled, ...p }: Props & { filled?: boolean }) => (
  <svg
    className={p.className ?? base}
    viewBox="0 0 24 24"
    fill={filled ? "currentColor" : "none"}
    stroke="currentColor"
    strokeWidth="1.6"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    <path d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1-5.4-2.9-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z" />
  </svg>
);
export const IconClock = (p: Props) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 7v5l3 2" />
  </Svg>
);
export const IconFlame = (p: Props) => (
  <Svg {...p}>
    <path d="M12 3s5 4 5 9a5 5 0 0 1-10 0c0-2 1-3 1-3s.5 2 2 2c0-3 2-5 2-8z" />
  </Svg>
);
export const IconAlert = (p: Props) => (
  <Svg {...p}>
    <path d="M12 4 2.5 20h19z" />
    <path d="M12 10v4M12 17.5v.5" />
  </Svg>
);
export const IconCheck = (p: Props) => (
  <Svg {...p}>
    <path d="m4 12 5 5L20 6" />
  </Svg>
);
export const IconX = (p: Props) => (
  <Svg {...p}>
    <path d="M6 6l12 12M18 6 6 18" />
  </Svg>
);
export const IconArrowLeft = (p: Props) => (
  <Svg {...p}>
    <path d="M19 12H5M11 6l-6 6 6 6" />
  </Svg>
);
export const IconArrowRight = (p: Props) => (
  <Svg {...p}>
    <path d="M5 12h14M13 6l6 6-6 6" />
  </Svg>
);
export const IconLink = (p: Props) => (
  <Svg {...p}>
    <path d="M10 13a5 5 0 0 0 7 0l2-2a5 5 0 0 0-7-7l-1 1" />
    <path d="M14 11a5 5 0 0 0-7 0l-2 2a5 5 0 0 0 7 7l1-1" />
  </Svg>
);
export const IconCamera = (p: Props) => (
  <Svg {...p}>
    <path d="M3 8a2 2 0 0 1 2-2h2l1.5-2h7L17 6h2a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
    <circle cx="12" cy="12.5" r="3.5" />
  </Svg>
);
export const IconPlay = (p: Props) => (
  <Svg {...p}>
    <path d="M7 4.5v15l12-7.5z" />
  </Svg>
);
export const IconPause = (p: Props) => (
  <Svg {...p}>
    <path d="M9 4v16M15 4v16" />
  </Svg>
);
export const IconTrash = (p: Props) => (
  <Svg {...p}>
    <path d="M4 7h16M10 7V4h4v3M6 7l1 13h10l1-13" />
  </Svg>
);
export const IconEdit = (p: Props) => (
  <Svg {...p}>
    <path d="M4 20h4L20 8l-4-4L4 16z" />
  </Svg>
);
export const IconRefresh = (p: Props) => (
  <Svg {...p}>
    <path d="M20 11a8 8 0 1 0-1.5 6" />
    <path d="M20 5v6h-6" />
  </Svg>
);
export const IconDownload = (p: Props) => (
  <Svg {...p}>
    <path d="M12 3v12M7 11l5 5 5-5M4 20h16" />
  </Svg>
);
export const IconSparkle = (p: Props) => (
  <Svg {...p}>
    <path d="M12 3.5 13.6 9l5.4 1.6-5.4 1.6L12 17.6 10.4 12.2 5 10.6 10.4 9z" />
  </Svg>
);
