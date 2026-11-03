export function Placeholder({ title }: { title: string }) {
  return (
    <div className="placeholder">
      <h2>{title}</h2>
      <p>Esta sección no forma parte del alcance actual del panel (el diseño solo define Inicio, Resultados y Reportes).</p>
    </div>
  );
}
