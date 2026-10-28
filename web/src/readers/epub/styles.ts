/** The look of a reflowable book: the reader's choices over the book's own CSS. */
export interface EpubLook {
  theme: "auto" | "light" | "sepia" | "dark";
  font: "publisher" | "serif" | "sans";
  size: number; // percent
  lineHeight: number;
  margin: number; // px
  columns: number;
  justify: boolean;
  flow: "paginated" | "scrolled";
}

export const THEMES = {
  light: { background: "#ffffff", color: "#1c1917", link: "#c2410c" },
  sepia: { background: "#f4ecd8", color: "#433422", link: "#9a3412" },
  dark: { background: "#121214", color: "#e7e5e4", link: "#fb923c" },
} as const;

const FONTS = {
  serif: '"Iowan Old Style", "Palatino Linotype", Georgia, serif',
  sans: '"Inter Variable", ui-sans-serif, system-ui, sans-serif',
};

export function bookStyles(look: EpubLook, colors: (typeof THEMES)[keyof typeof THEMES]): string {
  const font = look.font === "publisher" ? "" : `font-family: ${FONTS[look.font]} !important;`;
  return `
    @namespace epub "http://www.idpf.org/2007/ops";
    html { color-scheme: ${colors === THEMES.dark ? "dark" : "light"}; }
    html, body { background: ${colors.background} !important; color: ${colors.color} !important; }
    body { font-size: ${look.size}% !important; line-height: ${look.lineHeight} !important; ${font} }
    p, li, blockquote, dd { line-height: ${look.lineHeight} !important; text-align: ${look.justify ? "justify" : "start"}; hyphens: auto; -webkit-hyphens: auto; }
    ${font ? `p, li, blockquote, dd, div, span { ${font} }` : ""}
    a:any-link { color: ${colors.link} !important; }
    img, svg, video { max-width: 100%; height: auto; object-fit: contain; }
    pre { white-space: pre-wrap !important; }
    aside[epub|type~="footnote"] { display: none; }
  `;
}
