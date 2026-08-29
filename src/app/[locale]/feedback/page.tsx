import type { Metadata } from "next"
import { getMessages } from "next-intl/server"
import { Mail, ShieldCheck } from "lucide-react"
import { Button } from "@/components/ui/button"
import { PageStructuredData } from "@/components/page-structured-data"
import { Footer } from "@/components/layout/footer"
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
        <main id="main-content" className="min-h-screen bg-background flex flex-col">
            <div className="flex-1 w-full mx-auto max-w-4xl px-4 py-10 sm:px-6 md:px-8 md:py-14">
                <div className="max-w-2xl space-y-3">
                    <div className="inline-flex items-center gap-2 rounded-full border bg-muted/40 px-3 py-1 text-xs font-medium text-muted-foreground">
                        <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />
                        {copy.privateFeedbackTitle}
                    </div>
                    <h1 className="text-3xl font-semibold tracking-tight text-balance sm:text-4xl">{copy.title}</h1>
                    <p className="text-sm leading-6 text-muted-foreground text-pretty">{copy.metaDescription}</p>
                </div>

                <section className="mt-8 overflow-hidden rounded-2xl border bg-card shadow-sm">
                    <div className="p-5 sm:p-7">
                        <div className="flex flex-col gap-6 md:flex-row md:items-center md:justify-between">
                            <div className="min-w-0 space-y-3">
                                <h2 className="text-lg font-semibold tracking-tight">{copy.privateFeedbackTitle}</h2>
                                <p className="max-w-2xl text-sm leading-6 text-muted-foreground whitespace-pre-wrap text-pretty">
                                    {copy.privateFeedbackDescription}
                                </p>
                                <a
                                    href={`mailto:${FEEDBACK_CONFIG.supportEmail}`}
                                    className="inline-flex max-w-full items-center gap-2 break-all text-sm font-medium underline decoration-border underline-offset-4 hover:decoration-foreground"
                                >
                                    <Mail className="h-4 w-4 shrink-0" aria-hidden="true" />
                                    {FEEDBACK_CONFIG.supportEmail}
                                </a>
                            </div>
                            <Button asChild size="lg" className="min-h-11 shrink-0">
                                <a href={feedbackMailto}>
                                    <Mail className="h-4 w-4" aria-hidden="true" />
                                    {copy.emailAction}
                                </a>
                            </Button>
                        </div>
                    </div>
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
