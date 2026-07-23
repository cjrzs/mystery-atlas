import { AppHeader } from "@/components/app-header";
import { ArchiveBrowser } from "@/components/archive-browser";

export default async function HomePage({
  searchParams,
}: {
  searchParams: Promise<{ scope?: string }>;
}) {
  const { scope } = await searchParams;

  return (
    <div className="site-shell">
      <AppHeader />
      <ArchiveBrowser initialScope={scope === "private" ? "private" : "public"} />
    </div>
  );
}
