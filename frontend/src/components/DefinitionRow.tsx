/** One label/value pair of a `<dl className="grid grid-cols-[auto_1fr] …">`. */
export function DefinitionRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="tabular-nums">{children}</dd>
    </>
  )
}
