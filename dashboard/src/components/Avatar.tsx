/** Silueta neutra de candidato (el contrato de la API no incluye fotografias). */
export function Avatar({ color }: { color: string }) {
  return (
    <svg className="avatar" viewBox="0 0 40 40" aria-hidden="true">
      <circle cx="20" cy="20" r="20" fill="#e7eefa" />
      <path d="M6 36c1.5-7 7-10 14-10s12.5 3 14 10a20 20 0 01-28 0z" fill="#17305f" />
      <path d="M17 26l3 5 3-5z" fill="#fff" />
      <path d="M19.2 28h1.6l.8 6h-3.2z" fill={color} />
      <circle cx="20" cy="15" r="6.2" fill="#f2c9a0" />
      <path d="M13.8 14c.2-4.6 3.4-7 6.4-7s6 2.2 6.2 7c-1.4-2-3.2-3-6.2-3s-4.8 1-6.4 3z" fill="#2a2a35" />
    </svg>
  );
}
