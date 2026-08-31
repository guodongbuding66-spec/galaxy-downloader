import { getMessages } from "next-intl/server"

import { ViewportSideRailAd } from "@/components/ads/viewport-side-rail-ad"
import { FreeSupportCard } from "@/components/downloader/FreeSupportCard"
import { PlatformGuideCard } from "@/components/downloader/PlatformGuideCard"
import { QuickStartCard } from "@/components/downloader/QuickStartCard"
import { TodayStatsCard } from "@/components/downloader/TodayStatsCard"
import { StructuredData } from "@/components/structured-data"
import { Footer } from "@/components/layout/footer"
import type { Locale } from "@/lib/i18n/config"
import type { Dictionary } from "@/lib/i18n/types"

import { UnifiedDownloaderClient } from "./unified-downloader-client"

export default async function HomePage({
    params,
}: {
    params: Promise<{ locale: Locale }>
}) {
    const { locale } = await params
    const dict = await getMessages({ locale }) as Dictionary

    return (
        <>
            <StructuredData locale={locale} dict={dict} />
            <UnifiedDownloaderClient
                leftRail={
                    <div className="grid gap-4 md:col-span-2 md:grid-cols-3 xl:col-span-3">
                        <TodayStatsCard dict={dict} />
                        <QuickStartCard dict={dict} />
                        <FreeSupportCard dict={dict} />
                        <div className="md:col-span-3">
                            <ViewportSideRailAd slot="1341604736" showOn="desktop" height={250} />
                        </div>
                    </div>
                }
                rightRail={
                    <div className="space-y-4 md:col-span-2 xl:col-span-3">
                        <PlatformGuideCard dict={dict} />
                        <ViewportSideRailAd slot="6380909506" showOn="desktop" height={250} />
                    </div>
                }
                mobileAd={
                    <ViewportSideRailAd slot="5740014745" showOn="mobile" height={250} />
                }
                heroMeta={
                    <p className="text-center text-xs leading-5 text-muted-foreground text-pretty">
                        {dict.page.feedback}
                    </p>
                }
                footer={<Footer locale={locale} dict={dict} />}
            />
        </>
    )
}
