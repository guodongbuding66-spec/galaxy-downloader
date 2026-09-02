from __future__ import annotations

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected one {label} target, got {count}: {old[:160]!r}")
    return text.replace(old, new, 1)


def patch_download_card() -> None:
    path = Path("src/components/downloader/LocalEngineDownloadCard.tsx")
    text = path.read_text(encoding="utf-8")

    text = replace_once(
        text,
        '''  HardDriveDownload,
  Loader2,
  X,
''',
        '''  HardDriveDownload,
  Loader2,
  Pause,
  Play,
  Trash2,
  X,
''',
        "lucide imports",
    )
    text = replace_once(
        text,
        '''  cancelLocalEngineBridgeJob,
  cancelLocalEngineQueuedJob,
  getLocalEngineBridgeStatus,
''',
        '''  cancelLocalEngineBridgeJob,
  cancelLocalEngineQueuedJob,
  discardLocalEngineResumeJob,
  getLocalEngineBridgeStatus,
''',
        "discard bridge import",
    )
    text = replace_once(
        text,
        '''  LocalEngineBridgeSubmissionError,
  openLocalEngineDownloadFolder,
  submitLocalEngineBridgeJob,
''',
        '''  LocalEngineBridgeSubmissionError,
  openLocalEngineDownloadFolder,
  pauseLocalEngineBridgeJob,
  resumeLocalEngineBridgeJob,
  submitLocalEngineBridgeJob,
''',
        "pause resume bridge imports",
    )

    resume_copy = '''
type ResumeCopy = {
  pause: string;
  pausing: string;
  recoverable: string;
  resume: string;
  discard: string;
  continueMode: string;
  restartMode: string;
  paused: string;
  interrupted: string;
  resumeStarted: string;
  resumeDiscarded: string;
};

const RESUME_COPY: Record<string, ResumeCopy> = {
  zh: {
    pause: '暂停当前', pausing: '正在保存断点并暂停', recoverable: '可恢复任务', resume: '继续任务', discard: '放弃恢复',
    continueMode: '断点续传', restartMode: '重新开始', paused: '已暂停', interrupted: '意外中断',
    resumeStarted: '已开始继续任务', resumeDiscarded: '已放弃该任务的恢复状态',
  },
  'zh-tw': {
    pause: '暫停目前工作', pausing: '正在保存進度並暫停', recoverable: '可恢復工作', resume: '繼續工作', discard: '放棄恢復',
    continueMode: '斷點續傳', restartMode: '重新開始', paused: '已暫停', interrupted: '意外中斷',
    resumeStarted: '已開始繼續工作', resumeDiscarded: '已放棄此工作的恢復狀態',
  },
  en: {
    pause: 'Pause current', pausing: 'Saving progress and pausing', recoverable: 'Recoverable jobs', resume: 'Resume', discard: 'Discard recovery',
    continueMode: 'Continue from checkpoint', restartMode: 'Restart required', paused: 'Paused', interrupted: 'Interrupted',
    resumeStarted: 'Recovery started', resumeDiscarded: 'Recovery state discarded',
  },
  ja: {
    pause: '現在の処理を一時停止', pausing: '進捗を保存して停止中', recoverable: '再開可能なジョブ', resume: '再開', discard: '復旧状態を破棄',
    continueMode: 'チェックポイントから再開', restartMode: '最初から再開', paused: '一時停止', interrupted: '中断',
    resumeStarted: '再開を開始しました', resumeDiscarded: '復旧状態を破棄しました',
  },
  es: {
    pause: 'Pausar actual', pausing: 'Guardando progreso y pausando', recoverable: 'Tareas recuperables', resume: 'Reanudar', discard: 'Descartar recuperación',
    continueMode: 'Continuar desde punto guardado', restartMode: 'Reinicio requerido', paused: 'Pausada', interrupted: 'Interrumpida',
    resumeStarted: 'Recuperación iniciada', resumeDiscarded: 'Estado de recuperación descartado',
  },
  ru: {
    pause: 'Приостановить', pausing: 'Сохранение прогресса и остановка', recoverable: 'Восстанавливаемые задачи', resume: 'Продолжить', discard: 'Удалить восстановление',
    continueMode: 'Продолжить с контрольной точки', restartMode: 'Нужен перезапуск', paused: 'Приостановлено', interrupted: 'Прервано',
    resumeStarted: 'Восстановление запущено', resumeDiscarded: 'Состояние восстановления удалено',
  },
};

function resumeCopyFor(pathname: string | null): ResumeCopy {
  const locale = pathname?.split('/').filter(Boolean)[0] || 'en';
  return RESUME_COPY[locale] || RESUME_COPY.en;
}

'''
    text = replace_once(
        text,
        "function copyFor(pathname: string | null): Copy {\n",
        resume_copy + "function copyFor(pathname: string | null): Copy {\n",
        "resume copy dictionary",
    )
    text = replace_once(
        text,
        '''  const pathname = usePathname();
  const copy = copyFor(pathname);
''',
        '''  const pathname = usePathname();
  const copy = copyFor(pathname);
  const resumeCopy = resumeCopyFor(pathname);
''',
        "resume copy selection",
    )
    text = replace_once(
        text,
        '''  const [launching, setLaunching] = useState(false);
  const [cancellingQueuedJobId, setCancellingQueuedJobId] = useState<string | null>(null);
''',
        '''  const [launching, setLaunching] = useState(false);
  const [pausing, setPausing] = useState(false);
  const [controllingResumeJobId, setControllingResumeJobId] = useState<string | null>(null);
  const [cancellingQueuedJobId, setCancellingQueuedJobId] = useState<string | null>(null);
''',
        "resume control state",
    )
    text = replace_once(
        text,
        '''  const queuedJobs = bridge?.queuedJobs || [];
  const queueFull = Boolean(bridge?.busy && queueCapacity > 0 && queueLength >= queueCapacity);
''',
        '''  const queuedJobs = bridge?.queuedJobs || [];
  const resumeJobs = bridge?.resumeJobs || [];
  const queueFull = Boolean(bridge?.busy && queueCapacity > 0 && queueLength >= queueCapacity);
''',
        "resume jobs derived state",
    )

    handlers = '''

  const handlePause = async () => {
    if (pausing || !bridge?.canPause) return;
    setPausing(true);
    try {
      const message = await pauseLocalEngineBridgeJob();
      toast.message(resumeCopy.pausing, { description: message });
      await refreshBridge();
    } catch (error) {
      toast.error(resumeCopy.pause, { description: error instanceof Error ? error.message : String(error) });
    } finally {
      setPausing(false);
    }
  };

  const handleResume = async (jobId: string) => {
    if (controllingResumeJobId || bridge?.busy) return;
    setControllingResumeJobId(jobId);
    try {
      const message = await resumeLocalEngineBridgeJob(jobId);
      toast.success(resumeCopy.resumeStarted, { description: message });
      await refreshBridge();
    } catch (error) {
      await refreshBridge();
      toast.error(resumeCopy.resume, { description: error instanceof Error ? error.message : String(error) });
    } finally {
      setControllingResumeJobId(null);
    }
  };

  const handleDiscardResume = async (jobId: string) => {
    if (controllingResumeJobId) return;
    setControllingResumeJobId(jobId);
    try {
      const message = await discardLocalEngineResumeJob(jobId);
      toast.success(resumeCopy.resumeDiscarded, { description: message });
      await refreshBridge();
    } catch (error) {
      await refreshBridge();
      toast.error(resumeCopy.discard, { description: error instanceof Error ? error.message : String(error) });
    } finally {
      setControllingResumeJobId(null);
    }
  };
'''
    text = replace_once(
        text,
        "\n\n  const handleCancelQueued = async (jobId: string) => {\n",
        handlers + "\n\n  const handleCancelQueued = async (jobId: string) => {\n",
        "resume handlers",
    )

    resume_ui = '''

      {resumeJobs.length > 0 ? (
        <div className="mt-3 border-y" aria-label={resumeCopy.recoverable}>
          <div className="flex min-h-8 items-center justify-between gap-2 px-1 text-[11px] font-medium">
            <span>{resumeCopy.recoverable}</span>
            <span className="tabular-nums text-muted-foreground">{resumeJobs.length}</span>
          </div>
          <div className="divide-y border-t">
            {resumeJobs.map((resumeJob) => {
              const controlling = controllingResumeJobId === resumeJob.id;
              const recoveryLabel = resumeJob.resumeMode === 'continue' ? resumeCopy.continueMode : resumeCopy.restartMode;
              const stateLabel = resumeJob.state === 'paused' ? resumeCopy.paused : resumeCopy.interrupted;
              return (
                <div key={resumeJob.id} className="flex min-h-11 min-w-0 items-center gap-2 px-1 py-1.5">
                  <div className="min-w-0 flex-1">
                    <div className="flex min-w-0 items-center gap-2">
                      <span className="truncate text-xs font-medium" title={resumeJob.label}>{resumeJob.label}</span>
                      <span className="shrink-0 rounded border px-1 py-0.5 text-[9px] text-muted-foreground">{recoveryLabel}</span>
                    </div>
                    <div className="mt-0.5 flex min-w-0 items-center gap-2 text-[10px] text-muted-foreground">
                      <span className="truncate">{resumeJob.sourceHost || stateLabel}</span>
                      <span className="shrink-0 tabular-nums">{Math.round(resumeJob.progress)}%</span>
                      <span className="shrink-0">{resumeJob.downloaded}</span>
                    </div>
                  </div>
                  <button
                    type="button"
                    disabled={disabled || Boolean(bridge?.busy) || controllingResumeJobId !== null}
                    onClick={() => void handleResume(resumeJob.id)}
                    aria-label={`${resumeCopy.resume}: ${resumeJob.label}`}
                    title={`${resumeCopy.resume} · ${recoveryLabel}`}
                    className="ui-pressable inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-muted-foreground outline-none hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50"
                  >
                    {controlling ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> : <Play className="h-3.5 w-3.5" aria-hidden="true" />}
                  </button>
                  <button
                    type="button"
                    disabled={disabled || controllingResumeJobId !== null}
                    onClick={() => void handleDiscardResume(resumeJob.id)}
                    aria-label={`${resumeCopy.discard}: ${resumeJob.label}`}
                    title={resumeCopy.discard}
                    className="ui-pressable inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-muted-foreground outline-none hover:bg-destructive/10 hover:text-destructive focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50"
                  >
                    <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      ) : null}
'''
    text = replace_once(
        text,
        "\n\n      <div className={`mt-3 grid gap-2 ${hasCollection ? 'lg:grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)]' : ''}`}>\n",
        resume_ui + "\n\n      <div className={`mt-3 grid gap-2 ${hasCollection ? 'lg:grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)]' : ''}`}>\n",
        "recoverable jobs UI",
    )

    text = replace_once(
        text,
        '      <div className="mt-3 grid gap-1.5 sm:grid-cols-2">\n',
        "      <div className={`mt-3 grid gap-1.5 ${bridge?.busy ? 'sm:grid-cols-3' : 'sm:grid-cols-2'}`}>\n",
        "busy action grid",
    )
    text = replace_once(
        text,
        '''        {bridge?.busy ? (
          <>
            <Button type="button" variant="destructive" size="sm" onClick={() => void handleCancel()}>
''',
        '''        {bridge?.busy ? (
          <>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => void handlePause()}
              disabled={disabled || pausing || !bridge.canPause}
            >
              {pausing ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Pause className="h-4 w-4" aria-hidden="true" />}
              {resumeCopy.pause}
            </Button>
            <Button type="button" variant="destructive" size="sm" onClick={() => void handleCancel()}>
''',
        "pause active action",
    )

    path.write_text(text, encoding="utf-8")


def patch_continue_contract_test() -> None:
    path = Path("scripts/test-local-engine-policy.py")
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '''        self.assertIn("--ignore-config", command)
        self.assertIn("--no-playlist", command)
''',
        '''        self.assertIn("--ignore-config", command)
        self.assertIn("--continue", command)
        self.assertIn("--no-playlist", command)
''',
        "external continue contract test",
    )
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    patch_download_card()
    patch_continue_contract_test()
