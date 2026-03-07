import { memo } from "react";

export const TablePart = memo(function TablePart({
  headers,
  rows,
}: {
  headers?: string[];
  rows?: string[][];
}) {
  return (
    <div className="overflow-x-auto my-3 rounded-xl border border-border">
      <table className="min-w-full text-sm">
        {headers && (
          <thead>
            <tr className="bg-secondary">
              {headers.map((h, i) => (
                <th
                  key={i}
                  className="px-4 py-2.5 text-left font-semibold text-foreground"
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
        )}
        <tbody>
          {(rows || []).map((row, i) => (
            <tr
              key={i}
              className="border-t border-border hover:bg-secondary/50 transition-colors"
            >
              {row.map((cell, j) => (
                <td key={j} className="px-4 py-2.5">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
});
