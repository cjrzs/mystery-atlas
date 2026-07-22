import { AppHeader } from "@/components/app-header";
import { ArchiveBrowser } from "@/components/archive-browser";

export default function HomePage() {
  return (
    <div className="site-shell">
      <AppHeader />
      <ArchiveBrowser />
    </div>
  );
}

