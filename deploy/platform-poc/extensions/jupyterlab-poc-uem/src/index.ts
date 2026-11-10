import { JupyterFrontEnd, JupyterFrontEndPlugin } from '@jupyterlab/application';
import { PageConfig, URLExt } from '@jupyterlab/coreutils';
import { INotebookTracker, NotebookActions } from '@jupyterlab/notebook';
import { ServerConnection } from '@jupyterlab/services';

const sessionId = crypto.randomUUID();

async function emit(event: string, attributes: Record<string, unknown> = {}, duration_ms?: number, result?: string) {
  const settings = ServerConnection.makeSettings();
  const url = URLExt.join(settings.baseUrl, 'platform', 'telemetry');
  const body = { schema_version: '1.0', event, session_id: sessionId, trace_id: crypto.randomUUID(), attributes, duration_ms, result };
  try {
    await ServerConnection.makeRequest(url, { method: 'POST', body: JSON.stringify(body) }, settings);
  } catch (_) {
    // Telemetry must never break the notebook interaction path.
  }
}

const plugin: JupyterFrontEndPlugin<void> = {
  id: 'jupyterlab-poc-uem:plugin',
  autoStart: true,
  requires: [INotebookTracker],
  activate: (app: JupyterFrontEnd, notebooks: INotebookTracker) => {
    const started = performance.now();
    void app.restored.then(() => emit('lab_ready', { lab_version: PageConfig.getOption('appVersion') }, performance.now() - started, 'ok'));

    notebooks.currentChanged.connect((_sender, panel) => {
      if (!panel) return;
      void emit('notebook_activated', { document_type: 'notebook' });
      panel.sessionContext.statusChanged.connect((_context, status) => {
        void emit(status === 'dead' ? 'kernel_dead' : 'kernel_ready', { status });
      });
    });

    NotebookActions.executionScheduled.connect((_sender, args) => {
      void emit('cell_execute_start', { cell_type: args.cell.model.type });
    });
    NotebookActions.executed.connect((_sender, args) => {
      void emit('cell_execute_end', { cell_type: args.cell.model.type }, undefined, args.success ? 'ok' : 'error');
    });
    window.addEventListener('unhandledrejection', event => {
      void emit('js_error', { error_type: 'unhandled_rejection', message_hash: String(event.reason?.name ?? 'unknown') });
    });
  }
};

export default plugin;
