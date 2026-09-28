// Export, in Cycls: exported files go to the Cycls workspace, beside the design,
// never to the user's disk — one file per export (no zip; Cycls names and dedupes
// them). The rendering is upstream's. Replaces upstream src/app/document/export/
// create.ts (pinned in upstream.sha256) with the same actions.
import type { Editor, EditorState } from '@open-pencil/core/editor'
import type { ExportRequest, IORegistry } from '@open-pencil/core/io'

import {
  createExportTargetActions,
  getExportBaseName,
  getExportBytes,
  getExportFileName,
  getExportOptions,
  type ExportedFile
} from '@/app/document/export/files'
import type { ExportOptions } from '@/app/document/export/types'

import { exportFiles, isBound } from '../host'

export interface ExportTargetRequest {
  target: ExportRequest['target']
  formatId: string
  options?: ExportOptions
}

export function createDocumentExportActions(
  editor: Editor,
  state: EditorState,
  io: IORegistry,
  _downloadBlob: unknown
) {
  const { renderExportImage, getSelectionExportTarget, listSelectionExportFormats } =
    createExportTargetActions(editor, state, io)

  async function renderExportFile(
    target: ExportRequest['target'],
    formatId: string,
    options?: ExportOptions
  ): Promise<ExportedFile> {
    const format = io.getFormat(formatId)
    if (!format) throw new Error(`Unknown export format: ${formatId}`)
    const result = await io.exportContent(
      formatId,
      { graph: editor.graph, target },
      getExportOptions(formatId, options),
      editor.renderer ? { canvasKit: editor.renderer.ck, renderer: editor.renderer } : undefined
    )
    const baseName = getExportBaseName(editor.graph, target)
    return {
      bytes: getExportBytes(result.data),
      fileName: getExportFileName(baseName, formatId, result.extension, options),
      format: format.label,
      ext: `.${result.extension}`,
      mime: result.mimeType
    }
  }

  function send(files: ExportedFile[]): void {
    if (!isBound(state)) return
    exportFiles(files.map((f) => ({ name: f.fileName, mime: f.mime, bytes: f.bytes })))
  }

  async function exportTarget(target: ExportRequest['target'], formatId: string, options?: ExportOptions) {
    send([await renderExportFile(target, formatId, options)])
  }

  async function exportTargets(requests: ExportTargetRequest[]) {
    const files: ExportedFile[] = []
    for (const request of requests) {
      files.push(await renderExportFile(request.target, request.formatId, request.options))
    }
    send(files)
  }

  async function exportSelection(
    scale: number,
    formatId: 'png' | 'jpg' | 'webp' | 'svg' | 'pdf' | 'pptx' | 'fig'
  ) {
    await exportTarget(getSelectionExportTarget(), formatId, { scale })
  }

  return {
    renderExportImage,
    listSelectionExportFormats,
    exportTarget,
    exportTargets,
    exportSelection
  }
}
