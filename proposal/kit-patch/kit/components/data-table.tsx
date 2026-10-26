import { useState, type ReactNode } from "react";
import {
  flexRender, getCoreRowModel, getFilteredRowModel, getSortedRowModel, useReactTable,
  type ColumnDef, type SortingState, type FilterFn, type RowData, type Column, type Table as TanTable,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../ui/table";
import { useKitT } from "../strings";
import { cn } from "../lib/utils";

export type { ColumnDef } from "@tanstack/react-table";

declare module "@tanstack/react-table" {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  interface ColumnMeta<TData extends RowData, TValue> {
    /** "end" for numbers (amounts, quantities, %): head and cells end-aligned with tabular
     *  digits. Default: "end" when every value of the column's accessor is a number. */
    align?: "start" | "center" | "end";
    headerClassName?: string;
    cellClassName?: string;
    /** apps keep their own meta fields (e.g. `pinned`) */
    [key: string]: unknown;
  }
}

const ALIGN = { start: "text-start", center: "text-center", end: "text-end num" } as const;
/** The column's alignment: meta.align, else "end" when all its accessor values are numbers. */
function alignOf<T>(col: Column<T, unknown>, table: TanTable<T>): "start" | "center" | "end" {
  const m = col.columnDef.meta?.align;
  if (m) return m;
  if (!col.accessorFn) return "start";
  const rows = table.getCoreRowModel().rows;
  if (!rows.length) return "start";
  let seen = 0;
  for (const r of rows) {
    const v = r.getValue(col.id);
    if (v === null || v === undefined || v === "") continue;
    if (typeof v !== "number") return "start";
    seen++;
  }
  return seen ? "end" : "start";
}

/** shadcn's "data table" recipe: tanstack table rendered with shadcn Table. Sorting on
 *  every column with an accessor, a global text filter, keyboard-openable rows. shadcn's
 *  Table already scrolls sideways in its own container, so the page never does.
 *  Numeric columns (every accessor value a number, or `meta: {align: "end"}`) are
 *  end-aligned with tabular digits in both languages; a column whose cell formats a number
 *  from a non-numeric accessor needs `meta: {align: "end"}`. */
export function DataTable<T>({ data, columns, getRowId, onRowClick, initialSort = [], query = "", empty, minWidth = 640, className, rowLabel }: {
  data: T[];
  columns: ColumnDef<T, any>[];
  getRowId: (row: T) => string;
  onRowClick?: (row: T) => void;
  initialSort?: SortingState;
  /** global filter (case-insensitive substring over every accessor value) */
  query?: string;
  empty?: ReactNode;
  /** px before the table scrolls inside its box */
  minWidth?: number;
  className?: string;
  rowLabel?: (row: T) => string;
}) {
  const t = useKitT();
  const [sorting, setSorting] = useState<SortingState>(initialSort);
  const table = useReactTable({
    data, columns, getRowId,
    state: { sorting, globalFilter: query },
    onSortingChange: setSorting,
    globalFilterFn: includes as FilterFn<T>,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
  });
  const rows = table.getRowModel().rows;
  const align: Record<string, "start" | "center" | "end"> = {};
  for (const c of table.getAllLeafColumns()) align[c.id] = alignOf(c as Column<T, unknown>, table);
  return (
    // contain-inline-size: the table's min-width must never become its PARENT's min-content
    // (a grid/flex item would grow past the screen); it scrolls inside instead.
    <div className={cn("w-full rounded-xl border bg-card contain-inline-size", className)}>
      <Table style={{ minWidth }}>
        <TableHeader className="bg-muted/60">
          {table.getHeaderGroups().map((hg) => (
            <TableRow key={hg.id} className="hover:bg-transparent">
              {hg.headers.map((h) => {
                const sorted = h.column.getIsSorted();
                return (
                  <TableHead key={h.id} aria-sort={sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : undefined}
                    className={cn("text-xs", ALIGN[align[h.column.id] ?? "start"], h.column.columnDef.meta?.headerClassName)}>
                    {h.isPlaceholder ? null : h.column.getCanSort() ? (
                      <button type="button" onClick={h.column.getToggleSortingHandler()}
                        className={cn("-mx-2 inline-flex h-10 items-center gap-1 rounded-md px-2 hover:bg-accent hover:text-accent-foreground", align[h.column.id] === "end" && "flex-row-reverse")}>
                        {flexRender(h.column.columnDef.header, h.getContext())}
                        {sorted === "asc" ? <ArrowUp className="size-3.5" aria-label={t("sortAsc")} />
                          : sorted === "desc" ? <ArrowDown className="size-3.5" aria-label={t("sortDesc")} />
                          : <ArrowUpDown className="size-3.5 opacity-50" aria-hidden />}
                      </button>
                    ) : flexRender(h.column.columnDef.header, h.getContext())}
                  </TableHead>
                );
              })}
            </TableRow>
          ))}
        </TableHeader>
        <TableBody>
          {rows.map((r) => (
            <TableRow key={r.id}
              tabIndex={onRowClick ? 0 : undefined}
              aria-label={rowLabel ? rowLabel(r.original) : undefined}
              onClick={onRowClick ? () => onRowClick(r.original) : undefined}
              onKeyDown={onRowClick ? (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onRowClick(r.original); } } : undefined}
              className={cn(onRowClick && "cursor-pointer focus-visible:bg-muted/50 focus-visible:outline-none")}>
              {r.getVisibleCells().map((c) => <TableCell key={c.id} className={cn("py-2.5", ALIGN[align[c.column.id] ?? "start"], c.column.columnDef.meta?.cellClassName)}>{flexRender(c.column.columnDef.cell, c.getContext())}</TableCell>)}
            </TableRow>
          ))}
          {!rows.length && (
            <TableRow className="hover:bg-transparent">
              <TableCell colSpan={columns.length} className="h-24 text-center text-muted-foreground">{empty ?? t("noResults")}</TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
    </div>
  );
}

function includes<T>(row: { getValue: (id: string) => unknown; original: T }, columnId: string, q: string): boolean {
  if (!q) return true;
  const v = row.getValue(columnId);
  return v !== undefined && v !== null && String(v).toLowerCase().includes(q.toLowerCase());
}
