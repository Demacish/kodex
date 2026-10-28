import { encode } from "uqr";

/** A QR code as SVG, dark on white whatever the theme (scanners need that). */
export function QrCode({ value, label }: { value: string; label: string }) {
  const { data, size } = encode(value, { ecc: "M", border: 2 });
  let path = "";
  data.forEach((row, y) => row.forEach((dark, x) => {
    if (dark) path += `M${x} ${y}h1v1h-1z`;
  }));
  return (
    <svg viewBox={`0 0 ${size} ${size}`} role="img" aria-label={label} shapeRendering="crispEdges" className="size-44 rounded-lg bg-white">
      <path d={path} fill="#000" />
    </svg>
  );
}
