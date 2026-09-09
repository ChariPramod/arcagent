export function Metric({
  name,
  value,
  note,
}: {
  name: string;
  value: string;
  note: string;
}) {
  return (
    <div className="metric">
      <p>{name}</p>
      <strong>{value}</strong>
      <span>{note}</span>
    </div>
  );
}
