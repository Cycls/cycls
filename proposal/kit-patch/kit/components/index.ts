// The kit's own composites (built on kit/ui, shadcn's source). shadcn primitives are
// imported straight from their file, shadcn-style: import { Button } from "./kit/ui/button".
export { AppShell, DemoBanner, ErrorBoundary } from "./app-shell";
export { ThemeProvider, useTheme, type Theme } from "./theme";
export { Toolbar, LangToggle, ThemeToggle } from "./toolbar";
export { ResponsiveSheet, Confirm } from "./responsive-sheet";
export { Field, SimpleSelect } from "./field";
export { Segmented } from "./segmented";
export { StatusBadge, TONE_TEXT, type Tone } from "./status-badge";
export { EmptyState, Spinner } from "./empty-state";
export { DataTable, type ColumnDef } from "./data-table";
export { Kanban, type KanbanColumn, type KanbanProps } from "./kanban";
export { DatePicker } from "./date-picker";
export { Markdownish, MiniTable, MiniChart, DocMock, SafeImage, type ChartDatum } from "./rich";
export { ExamplesShowcase, ResultView, TryPrompt, type Example, type ExampleCategory, type ResultBlock } from "./showcase";
export { ContentResult, SeriesChart, useText } from "./content-result";
export { EmailImport, EmailSourceBadge, emailImportRules, isEmailSource, EMAIL_PERIODS, type EmailSource, type EmailPeriod, type EmailImportQuery } from "./email-import";
export { AutoText, Ltr, Amount, UnreadableValue, UnreadableNotice } from "./text";
export { LoadExampleButton } from "./empty-state";
