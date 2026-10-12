import type { Metadata } from "next"
import Image from "next/image"
import Link from "next/link"
import { getMessages } from "next-intl/server"
import { ArrowUpRight, Mail, MessageSquare } from "lucide-react"
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
    const title = dict.contactPage.metaTitle
    const description = dict.contactPage.metaDescription
    const url = buildLocaleUrl(locale, "/contact")

    return {
        title,
        description,
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
            languages: buildLanguageAlternates("/contact"),
        },
    }
}

export default async function ContactPage({
    params,
}: {
    params: Promise<{ locale: Locale }>
}) {
    const { locale } = await params
    const dict = await getMessages({ locale }) as Dictionary
    const copy = dict.contactPage

    return (
        <main id="main-content" className="flex min-h-screen flex-col bg-background">
            <div className="mx-auto w-full max-w-4xl flex-1 px-4 py-10 sm:px-6 md:px-8 md:py-14">
                <header className="max-w-2xl border-b pb-7">
                    <h1 className="text-balance text-3xl font-semibold tracking-[-0.03em] sm:text-4xl">{copy.title}</h1>
                    <p className="mt-3 max-w-[65ch] text-pretty text-sm leading-6 text-muted-foreground">{copy.intro}</p>
                </header>

                <div className="divide-y border-b">
                    <section className="grid gap-4 py-6 md:grid-cols-[44px_minmax(0,1fr)_auto] md:items-start">
                        <div className="flex h-10 w-10 items-center justify-center rounded-md border bg-[hsl(var(--surface-subtle))]">
                            <MessageSquare className="h-4 w-4" aria-hidden="true" />
                        </div>
                        <div className="min-w-0">
                            <h2 className="text-sm font-semibold">{copy.feedback}</h2>
                            <p className="mt-1 max-w-2xl text-sm leading-6 text-muted-foreground">{copy.feedbackHint}</p>
                        </div>
                        <Link
                            href={`/${locale}/feedback`}
                            className="ui-target inline-flex items-center gap-1.5 self-start rounded-md px-1 text-sm font-medium underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
                        >
                            {copy.feedback}
                            <ArrowUpRight className="h-4 w-4" aria-hidden="true" />
                        </Link>
                    </section>

                    <section className="grid gap-4 py-6 md:grid-cols-[44px_minmax(0,1fr)_auto] md:items-start">
                        <div className="flex h-10 w-10 items-center justify-center rounded-md border bg-[hsl(var(--surface-subtle))]">
                            <Mail className="h-4 w-4" aria-hidden="true" />
                        </div>
                        <div className="min-w-0">
                            <h2 className="break-all text-sm font-semibold">{FEEDBACK_CONFIG.supportEmail}</h2>
                            <p className="mt-1 max-w-2xl text-sm leading-6 text-muted-foreground">{copy.feedbackHint}</p>
                        </div>
                        <a
                            href={`mailto:${FEEDBACK_CONFIG.supportEmail}`}
                            className="ui-target inline-flex items-center gap-1.5 self-start rounded-md px-1 text-sm font-medium underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
                        >
                            <Mail className="h-4 w-4" aria-hidden="true" />
                            {FEEDBACK_CONFIG.supportEmail}
                        </a>
                    </section>

                    <section className="grid gap-4 py-6 md:grid-cols-[44px_minmax(0,1fr)_auto] md:items-start">
                        <div className="flex h-10 w-10 items-center justify-center rounded-md border bg-[hsl(var(--surface-subtle))]">
                            <Image src="/platform-icons/github.svg" alt="" width={16} height={16} aria-hidden="true" className="dark:invert" />
                        </div>
                        <div className="min-w-0">
                            <h2 className="text-sm font-semibold">{copy.github}</h2>
                            <p className="mt-1 max-w-2xl text-sm leading-6 text-muted-foreground">{copy.githubHint}</p>
                        </div>
                        <a
                            href="https://github.com/guodongbuding66-spec/galaxy-downloader"
                            target="_blank"
                            rel="noopener noreferrer"
                            className="ui-target inline-flex items-center gap-1.5 self-start rounded-md px-1 text-sm font-medium underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
                        >
                            {copy.github}
                            <ArrowUpRight className="h-4 w-4" aria-hidden="true" />
                        </a>
                    </section>
                </div>

                <nav className="mt-6 flex flex-wrap gap-x-3 gap-y-2 text-sm text-muted-foreground" aria-label={dict.common.relatedPages}>
                    <span>{dict.common.relatedPages}:</span>
                    <Link className="underline underline-offset-4 hover:text-foreground" href={`/${locale}`}>{dict.common.home}</Link>
                    <Link className="underline underline-offset-4 hover:text-foreground" href={`/${locale}/feedback`}>{dict.feedbackPage.title}</Link>
                    <Link className="underline underline-offset-4 hover:text-foreground" href={`/${locale}/privacy`}>{dict.common.privacy}</Link>
                    <Link className="underline underline-offset-4 hover:text-foreground" href={`/${locale}/terms`}>{dict.common.terms}</Link>
                </nav>
            </div>

            <Footer locale={locale} dict={dict} />

            <PageStructuredData
                locale={locale}
                pageTitle={copy.title}
                pageDescription={copy.intro}
                path="/contact"
                breadcrumbs={[
                    { name: dict.common.home, path: "" },
                    { name: copy.title, path: "/contact" },
                ]}
            />
        </main>
    )
}
