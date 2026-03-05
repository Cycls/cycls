export function TablePart({
  headers,
  rows,
}: {
  headers?: string[];
  rows?: string[][];
}) {
  return (
    <div className="overflow-x-auto my-3">
      <table className="min-w-full border border-[var(--border-color)] rounded-lg overflow-hidden">
        {headers && (
          <thead className="bg-[var(--bg-secondary)]">
            <tr>
              {headers.map((h, i) => (
                <th key={i} className="px-4 py-2 text-left font-medium">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
        )}
        <tbody>
          {(rows || []).map((row, i) => (
            <tr key={i} className={i % 2 ? "bg-[var(--bg-secondary)]" : ""}>
              {row.map((cell, j) => (
                <td
                  key={j}
                  className="px-4 py-2 border-t border-[var(--border-color)]"
                >
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
