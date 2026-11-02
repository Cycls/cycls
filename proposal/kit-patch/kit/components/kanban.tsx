import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  DndContext, DragOverlay, KeyboardSensor, PointerSensor, TouchSensor, closestCorners, useDroppable, useSensor, useSensors,
  type Announcements, type DragEndEvent, type DragOverEvent, type DragStartEvent, type KeyboardCoordinateGetter, type UniqueIdentifier,
} from "@dnd-kit/core";
import { SortableContext, arrayMove, sortableKeyboardCoordinates, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { holdRefresh } from "../cycls";
import { useKitT } from "../strings";
import { cn } from "../lib/utils";

export interface KanbanColumn { id: string; title: ReactNode; label: string; accent?: string; footer?: ReactNode }

export interface KanbanProps<T> {
  columns: KanbanColumn[];
  items: T[];
  getId: (item: T) => string;
  getColumn: (item: T) => string;
  getOrder: (item: T) => number;
  /** `order` is the new sort key; `renumber` lists other cards whose order had to change
   *  (only when two cards shared one order). Write each with cycls.update. */
  onMove: (id: string, column: string, order: number, renumber: { id: string; order: number }[]) => void;
  renderCard: (item: T, state: { overlay: boolean }) => ReactNode;
  onOpen?: (item: T) => void;
  /** spoken name of a card, for the drag announcements */
  itemLabel: (item: T) => string;
  emptyColumn?: ReactNode;
  readOnly?: boolean;
}

const COL = "col:";

// sortableKeyboardCoordinates takes any droppable whose left edge is right of the card's
// as "to the right" — and cards in one column differ by sub-pixels (24.3 vs 24.5), so
// ArrowRight first lands on a sibling. Horizontal arrows here only see targets at least
// half a card away, i.e. in another column.
const kanbanCoordinates: KeyboardCoordinateGetter = (event, args) => {
  const { collisionRect, droppableRects, droppableContainers } = args.context;
  if (!collisionRect || (event.code !== "ArrowLeft" && event.code !== "ArrowRight")) return sortableKeyboardCoordinates(event, args);
  const half = collisionRect.width / 2;
  const enabled = droppableContainers.getEnabled().filter((e) => {
    const r = droppableRects.get(e.id);
    return !!r && (event.code === "ArrowRight" ? r.left > collisionRect.left + half : r.left < collisionRect.left - half);
  });
  const only = new Proxy(droppableContainers, {
    get(t, k) {
      if (k === "getEnabled") return () => enabled;
      const v = Reflect.get(t, k, t);
      return typeof v === "function" ? v.bind(t) : v;
    },
  });
  return sortableKeyboardCoordinates(event, { ...args, context: { ...args.context, droppableContainers: only } });
};
type Board = Record<string, string[]>;

/** Columns side by side; on a phone they scroll sideways in their own strip (snap).
 *  Drag with mouse, touch (long-press) or keyboard (Space, arrows, Space). Enter opens. */
export function Kanban<T>(p: KanbanProps<T>) {
  const t = useKitT();
  const byId = useMemo(() => new Map(p.items.map((x) => [p.getId(x), x])), [p.items, p.getId]);
  const fromProps = useMemo<Board>(() => {
    const b: Board = Object.fromEntries(p.columns.map((c) => [c.id, [] as string[]]));
    const sorted = [...p.items].sort((a, b) => p.getOrder(a) - p.getOrder(b) || (p.getId(a) < p.getId(b) ? -1 : 1));
    for (const it of sorted) (b[p.getColumn(it)] ??= []).push(p.getId(it));
    return b;
  }, [p.items, p.columns, p.getColumn, p.getOrder, p.getId]);
  const [board, setBoard] = useState<Board>(fromProps);
  const [active, setActive] = useState<string | null>(null);
  const release = useRef<null | (() => void)>(null);
  useEffect(() => { if (!active) setBoard(fromProps); }, [fromProps, active]);
  useEffect(() => () => release.current?.(), []);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 220, tolerance: 8 } }),
    useSensor(KeyboardSensor, { coordinateGetter: kanbanCoordinates, keyboardCodes: { start: ["Space"], cancel: ["Escape"], end: ["Space", "Enter"] } }),
  );

  const containerOf = (id: UniqueIdentifier): string | undefined => {
    const s = String(id);
    if (s.startsWith(COL)) return s.slice(COL.length);
    return Object.keys(board).find((c) => board[c].includes(s));
  };
  const colLabel = (id?: string) => p.columns.find((c) => c.id === id)?.label ?? "";
  const name = (id: UniqueIdentifier) => { const it = byId.get(String(id)); return it ? p.itemLabel(it) : String(id); };

  const announcements: Announcements = {
    onDragStart: ({ active: a }) => t("picked", { item: name(a.id) }),
    onDragOver: ({ active: a, over }) => (over ? t("movedOver", { item: name(a.id), column: colLabel(containerOf(over.id)) }) : undefined),
    onDragEnd: ({ active: a, over }) => (over ? t("dropped", { item: name(a.id), column: colLabel(containerOf(over.id)) }) : t("cancelled")),
    onDragCancel: () => t("cancelled"),
  };

  function onStart(e: DragStartEvent) {
    setActive(String(e.active.id));
    release.current?.();
    release.current = holdRefresh();
  }
  function onOver(e: DragOverEvent) {
    const { active: a, over } = e;
    if (!over) return;
    const from = containerOf(a.id), to = containerOf(over.id);
    if (!from || !to || from === to) return;
    setBoard((b) => {
      const src = b[from].filter((x) => x !== a.id);
      const dst = [...b[to]];
      const overIdx = String(over.id).startsWith(COL) ? dst.length : Math.max(0, dst.indexOf(String(over.id)));
      dst.splice(overIdx, 0, String(a.id));
      return { ...b, [from]: src, [to]: dst };
    });
  }
  function finish() { setActive(null); release.current?.(); release.current = null; }
  function onEnd(e: DragEndEvent) {
    const { active: a, over } = e;
    const id = String(a.id);
    if (!over) { finish(); setBoard(fromProps); return; }
    const col = containerOf(over.id) ?? containerOf(a.id);
    if (!col) { finish(); return; }
    let list = board[col];
    const oi = list.indexOf(String(over.id));
    const ai = list.indexOf(id);
    if (ai >= 0 && oi >= 0 && ai !== oi) list = arrayMove(list, ai, oi);
    setBoard((b) => ({ ...b, [col]: list }));
    const i = list.indexOf(id);
    const ord = (x: string) => { const it = byId.get(x); return it ? p.getOrder(it) : 0; };
    const prev = i > 0 ? ord(list[i - 1]) : undefined;
    const next = i < list.length - 1 ? ord(list[i + 1]) : undefined;
    let order: number;
    let renumber: { id: string; order: number }[] = [];
    if (prev !== undefined && next !== undefined) order = (prev + next) / 2;
    else if (prev !== undefined) order = prev + 1024;
    else if (next !== undefined) order = next - 1024;
    else order = 0;
    if ((prev !== undefined && order <= prev) || (next !== undefined && order >= next) || !Number.isFinite(order)) {
      // ties (e.g. the agent wrote order 0 everywhere): renumber this column
      renumber = list.filter((x) => x !== id).map((x, k) => ({ id: x, order: (k + (k >= i ? 1 : 0)) * 1024 }));
      order = i * 1024;
    }
    const item = byId.get(id);
    const moved = !item || p.getColumn(item) !== col || p.getOrder(item) !== order;
    finish();
    if (moved) p.onMove(id, col, order, renumber.filter((r) => { const it = byId.get(r.id); return !it || p.getOrder(it) !== r.order; }));
  }

  const activeItem = active ? byId.get(active) : undefined;
  return (
    <DndContext sensors={p.readOnly ? undefined : sensors} collisionDetection={closestCorners}
      accessibility={{ announcements, screenReaderInstructions: { draggable: t("dragHint") } }}
      onDragStart={onStart} onDragOver={onOver} onDragEnd={onEnd} onDragCancel={() => { finish(); setBoard(fromProps); }}>
      {/* relative: an overflow box only clips absolutely-positioned descendants (sr-only text,
          badges) when it is their containing block — without it they widen the PAGE. */}
      <div className="relative flex snap-x snap-mandatory gap-3 overflow-x-auto contain-inline-size lg:contain-none overscroll-x-contain px-3 pb-3 sm:px-4 lg:grid lg:snap-none lg:overflow-visible"
        style={{ gridTemplateColumns: `repeat(${p.columns.length}, minmax(0, 1fr))` }}>
        {p.columns.map((c) => (
          <Column key={c.id} col={c} ids={board[c.id] ?? []} count={(board[c.id] ?? []).length} empty={p.emptyColumn}>
            {(board[c.id] ?? []).map((id) => {
              const it = byId.get(id);
              return it ? <Card key={id} id={id} disabled={p.readOnly} onOpen={p.onOpen ? () => p.onOpen!(it) : undefined}>{p.renderCard(it, { overlay: false })}</Card> : null;
            })}
          </Column>
        ))}
      </div>
      <DragOverlay>{activeItem ? <div className="cursor-grabbing rotate-1 shadow-lg">{p.renderCard(activeItem, { overlay: true })}</div> : null}</DragOverlay>
    </DndContext>
  );
}

function Column({ col, ids, count, empty, children }: { col: KanbanColumn; ids: string[]; count: number; empty?: ReactNode; children: ReactNode }) {
  const { setNodeRef, isOver } = useDroppable({ id: COL + col.id });
  return (
    <section aria-label={col.label} className="flex w-[min(18rem,80vw)] shrink-0 snap-start flex-col rounded-xl bg-muted lg:w-auto">
      <header className="flex items-center gap-2 px-3 pb-1 pt-3">
        {col.accent && <span aria-hidden className="size-2 shrink-0 rounded-full" style={{ background: col.accent }} />}
        <h3 className="min-w-0 flex-1 truncate text-sm font-semibold">{col.title}</h3>
        <span className="num rounded-full bg-card px-2 text-xs text-muted-foreground">{count}</span>
      </header>
      <SortableContext id={col.id} items={ids} strategy={verticalListSortingStrategy}>
        <div ref={setNodeRef} className={cn("flex min-h-24 flex-1 flex-col gap-2 p-2", isOver && "rounded-xl ring-2 ring-ring ring-inset")}>
          {children}
          {!count && empty && <div className="grid flex-1 place-items-center px-2 py-6 text-center text-xs text-muted-foreground">{empty}</div>}
        </div>
      </SortableContext>
      {col.footer && <div className="px-2 pb-2">{col.footer}</div>}
    </section>
  );
}

function Card({ id, children, onOpen, disabled }: { id: string; children: ReactNode; onOpen?: () => void; disabled?: boolean }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id, disabled });
  return (
    <div ref={setNodeRef} {...attributes} {...listeners}
      data-card-id={id}
      onClick={onOpen}
      onKeyDown={(e) => {
        listeners?.onKeyDown?.(e);
        if (!isDragging && !e.defaultPrevented && e.key === "Enter" && onOpen) { e.preventDefault(); onOpen(); }
      }}
      style={{ transform: CSS.Translate.toString(transform), transition }}
      className={cn("touch-manipulation rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-ring", isDragging && "opacity-40")}>
      {children}
    </div>
  );
}
