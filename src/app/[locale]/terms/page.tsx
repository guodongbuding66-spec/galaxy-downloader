import type { Metadata } from "next"
import Link from "next/link"
import { getMessages } from "next-intl/server"
import { Footer } from "@/components/layout/footer"
import { PageStructuredData } from "@/components/page-structured-data"
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
    const title = dict.termsPage.metaTitle
    const description = dict.termsPage.metaDescription
    const url = buildLocaleUrl(locale, "/terms")

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
            images: ["/og/terms.png"],
        },
        twitter: {
            card: "summary_large_image",
            title,
            description,
            images: ["/og/terms.png"],
        },
        alternates: {
            canonical: url,
            languages: buildLanguageAlternates("/terms"),
        },
    }
}

export default async function TermsPage({
    params,
}: {
    params: Promise<{ locale: Locale }>
}) {
    const { locale } = await params
    const dict = await getMessages({ locale }) as Dictionary
    const copy = dict.termsPage

    return (
        <main id="main-content" className="flex min-h-screen flex-col bg-background">
            <article className="mx-auto w-full max-w-3xl flex-1 px-4 py-10 sm:px-6 md:px-8 md:py-14">
                <header className="border-b pb-7">
                    <h1 className="text-balance text-3xl font-semibold tracking-[-0.03em] sm:text-4xl">{copy.title}</h1>
                    <p className="mt-3 max-w-[65ch] text-pretty text-sm leading-6 text-muted-foreground">{copy.intro}</p>
                    <p className="mt-4 text-xs font-medium text-muted-foreground">{copy.updated}</p>
                </header>

                <ol className="divide-y border-b text-sm leading-6">
                    {copy.points.map((point, index) => (
                        <li key={point} className="grid gap-3 py-5 sm:grid-cols-[32px_minmax(0,1fr)]">
                            <span className="font-mono text-xs tabular-nums text-muted-foreground" aria-hidden="true">
                                {String(index + 1).padStart(2, '0')}
                            </span>
                            <p className="max-w-[68ch] text-pretty text-muted-foreground">{point}</p>
                        </li>
                    ))}
                </ol>

                <nav className="mt-6 flex flex-wrap gap-x-3 gap-y-2 text-sm text-muted-foreground" aria-label={dict.common.relatedPages}>
                    <span>{dict.common.relatedPages}:</span>
                    <Link className="underline underline-offset-4 hover:text-foreground" href={`/${locale}/privacy`}>{dict.common.privacy}</Link>
                    <Link className="underline underline-offset-4 hover:text-foreground" href={`/${locale}/contact`}>{dict.common.contact}</Link>
                </nav>
            </article>

            <Footer locale={locale} dict={dict} />

            <PageStructuredData
                locale={locale}
                pageTitle={copy.title}
                pageDescription={copy.intro}
                path="/terms"
                breadcrumbs={[
                    { name: dict.common.home, path: "" },
                    { name: copy.title, path: "/terms" },
                ]}
            />
        </main>
    )
}
