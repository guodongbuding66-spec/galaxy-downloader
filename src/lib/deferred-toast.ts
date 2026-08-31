'use client'

type ToastApi = typeof import('sonner').toast
type ToastArgs = Parameters<ToastApi>
type ToastSuccessArgs = Parameters<ToastApi['success']>
type ToastErrorArgs = Parameters<ToastApi['error']>
type ToastInfoArgs = Parameters<ToastApi['info']>
type ToastWarningArgs = Parameters<ToastApi['warning']>
type ToastMessageArgs = Parameters<ToastApi['message']>

type DeferredToast = ((...args: ToastArgs) => void) & {
    success: (...args: ToastSuccessArgs) => void
    error: (...args: ToastErrorArgs) => void
    info: (...args: ToastInfoArgs) => void
    warning: (...args: ToastWarningArgs) => void
    message: (...args: ToastMessageArgs) => void
}

let toastApiPromise: Promise<ToastApi> | null = null

function getToastApi(): Promise<ToastApi> {
    if (!toastApiPromise) {
        toastApiPromise = import('sonner').then((mod) => mod.toast)
    }
    return toastApiPromise
}

function runToastTask(task: (toastApi: ToastApi) => void) {
    void getToastApi()
        .then(task)
        .catch(() => {
            // Ignore toast loading failures to avoid impacting main interactions.
        })
}

const baseToast = (...args: ToastArgs) => {
    runToastTask((toastApi) => {
        toastApi(...args)
    })
}

export const toast: DeferredToast = Object.assign(baseToast, {
    success: (...args: ToastSuccessArgs) => {
        runToastTask((toastApi) => {
            toastApi.success(...args)
        })
    },
    error: (...args: ToastErrorArgs) => {
        runToastTask((toastApi) => {
            toastApi.error(...args)
        })
    },
    info: (...args: ToastInfoArgs) => {
        runToastTask((toastApi) => {
            toastApi.info(...args)
        })
    },
    warning: (...args: ToastWarningArgs) => {
        runToastTask((toastApi) => {
            toastApi.warning(...args)
        })
    },
    message: (...args: ToastMessageArgs) => {
        runToastTask((toastApi) => {
            toastApi.message(...args)
        })
    },
})
