import type { Metadata } from "next"
import { getMessages } from "next-intl/server"
import { Mail, ShieldCheck } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Footer } from "@/components/layout/footer"
import { PageStructuredData } from "@/components/page-structured-data"
import { FEEDBACK_CONFIG } from "@/lib/feedback-config"
import type { Locale } from "@/lib/i18n/config"
import type { Dictionary } from "@/lib/i18n/types"
import {
    buildLanguageAlternates,
    buildLocaleUrl,
    buildOpenGraphLocaleAlternates,
    localeToOpenGraphLocale,
} from "@/lib/seo"

export async function generateMetadata({
    params,
}: {
    params: Promise<{ locale: Locale }>
}): Promise<Metadata> {
    const { locale } = await params
    const dict = await getMessages({ locale }) as Dictionary
    const title = dict.feedbackPage.metaTitle
    const description = dict.feedbackPage.metaDescription
    const url = buildLocaleUrl(locale, "/feedback")

    return {
        title,
        description,
        robots: {
            index: false,
            follow: true,
            googleBot: {
                index: false,
                follow: true,
            },
        },
        openGraph: {
            title,
            description,
            url,
            siteName: dict.metadata.siteName,
            locale: localeToOpenGraphLocale(locale),
            alternateLocale: buildOpenGraphLocaleAlternates(locale),
            type: "website",
            images: ["/og/contact.png"],
        },
        twitter: {
            card: "summary_large_image",
            title,
            description,
            images: ["/og/contact.png"],
        },
        alternates: {
            canonical: url,
            languages: buildLanguageAlternates("/feedback"),
        },
    }
}

export default async function FeedbackPage({
    params,
}: {
    params: Promise<{ locale: Locale }>
}) {
    const { locale } = await params
    const dict = await getMessages({ locale }) as Dictionary
    const copy = dict.feedbackPage
    const emailSubject = encodeURIComponent(`[Feedback] Galaxy Downloader`)
    const emailBody = encodeURIComponent(copy.emailTemplateBody || '')
    const feedbackMailto = `mailto:${FEEDBACK_CONFIG.supportEmail}?subject=${emailSubject}&body=${emailBody}`

    return (
        <main id="main-content" className="flex min-h-screen flex-col bg-background">
            <div className="mx-auto w-full max-w-4xl flex-1 px-4 py-10 sm:px-6 md:px-8 md:py-14">
                <header className="max-w-2xl border-b pb-7">
                    <div className="mb-4 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                        <ShieldCheck className="h-4 w-4" aria-hidden="true" />
                        <span>{copy.privateFeedbackTitle}</span>
                    </div>
                    <h1 className="text-balance text-3xl font-semibold tracking-[-0.03em] sm:text-4xl">{copy.title}</h1>
                    <p className="mt-3 max-w-[65ch] text-pretty text-sm leading-6 text-muted-foreground">{copy.metaDescription}</p>
                </header>

                <section className="grid gap-6 border-b py-7 md:grid-cols-[minmax(0,1fr)_auto] md:items-center">
                    <div className="min-w-0">
                        <h2 className="text-lg font-semibold tracking-[-0.02em]">{copy.privateFeedbackTitle}</h2>
                        <p className="mt-2 max-w-2xl whitespace-pre-wrap text-pretty text-sm leading-6 text-muted-foreground">
                            {copy.privateFeedbackDescription}
                        </p>
                        <a
                            href={`mailto:${FEEDBACK_CONFIG.supportEmail}`}
                            className="mt-4 inline-flex max-w-full items-center gap-2 break-all rounded-sm text-sm font-medium underline decoration-border underline-offset-4 hover:decoration-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
                        >
                            <Mail className="h-4 w-4 shrink-0" aria-hidden="true" />
                            {FEEDBACK_CONFIG.supportEmail}
                        </a>
                    </div>
                    <Button asChild size="lg" className="w-full md:w-auto md:shrink-0">
                        <a href={feedbackMailto}>
                            <Mail className="h-4 w-4" aria-hidden="true" />
                            {copy.emailAction}
                        </a>
                    </Button>
                </section>
            </div>

            <Footer locale={locale} dict={dict} />

            <PageStructuredData
                locale={locale}
                pageTitle={copy.title}
                pageDescription={copy.metaDescription}
                path="/feedback"
                breadcrumbs={[
                    { name: dict.common.home, path: "" },
                    { name: copy.title, path: "/feedback" },
                ]}
            />
        </main>
    )
}
