import { Workbench } from "@/components/workbench";

export default async function WorkPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return <Workbench slug={slug} />;
}
