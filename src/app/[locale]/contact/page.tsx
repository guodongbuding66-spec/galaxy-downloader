import type { Metadata } from "next"
import Image from "next/image"
import Link from "next/link"
import { getMessages } from "next-intl/server"
import { Mail, MessageSquare } from "lucide-react"
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
        <main id="main-content" className="min-h-screen bg-background">
            <div className="max-w-4xl mx-auto px-4 sm:px-6 md:px-8 py-10 md:py-14 space-y-8">
                <div className="max-w-2xl space-y-3">
                    <h1 className="text-3xl font-semibold tracking-tight text-balance sm:text-4xl">{copy.title}</h1>
                    <p className="text-sm text-muted-foreground leading-6 text-pretty">{copy.intro}</p>
                </div>

                <div className="grid gap-4 md:grid-cols-2">
                    <section className="rounded-2xl border bg-card p-5 shadow-sm space-y-3">
                        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-muted">
                            <MessageSquare className="h-4 w-4" aria-hidden="true" />
                        </div>
                        <Link href={`/${locale}/feedback`} className="block text-sm font-semibold underline decoration-border underline-offset-4 hover:decoration-foreground">
                            {copy.feedback}
                        </Link>
                        <p className="text-sm leading-6 text-muted-foreground">{copy.feedbackHint}</p>
                    </section>

                    <section className="rounded-2xl border bg-card p-5 shadow-sm space-y-3">
                        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-muted">
                            <Mail className="h-4 w-4" aria-hidden="true" />
                        </div>
                        <a href={`mailto:${FEEDBACK_CONFIG.supportEmail}`} className="block break-all text-sm font-semibold underline decoration-border underline-offset-4 hover:decoration-foreground">
                            {FEEDBACK_CONFIG.supportEmail}
                        </a>
                        <p className="text-sm leading-6 text-muted-foreground">{copy.feedbackHint}</p>
                    </section>
                </div>

                <section className="rounded-2xl border bg-card p-5 shadow-sm space-y-3">
                    <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-muted">
                        <Image
                            src="/platform-icons/github.svg"
                            alt=""
                            width={16}
                            height={16}
                            aria-hidden="true"
                            className="dark:invert"
                        />
                    </div>
                    <a
                        href="https://github.com/guodongbuding66-spec/galaxy-downloader"
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-sm font-semibold underline decoration-border underline-offset-4 hover:decoration-foreground"
                    >
                        {copy.github}
                    </a>
                    <p className="text-sm leading-6 text-muted-foreground">{copy.githubHint}</p>
                </section>

                <p className="text-sm text-muted-foreground">
                    {dict.common.relatedPages}
                    {": "}
                    <Link className="underline underline-offset-4" href={`/${locale}`}>{dict.common.home}</Link>
                    {' · '}
                    <Link className="underline underline-offset-4" href={`/${locale}/feedback`}>{dict.feedbackPage.title}</Link>
                    {' · '}
                    <Link className="underline underline-offset-4" href={`/${locale}/privacy`}>{dict.common.privacy}</Link>
                    {' · '}
                    <Link className="underline underline-offset-4" href={`/${locale}/terms`}>{dict.common.terms}</Link>
                </p>
            </div>
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
