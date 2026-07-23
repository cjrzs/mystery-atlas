import { Workbench } from "@/components/workbench";

export default async function PrivateWorkPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <Workbench libraryItemId={id} />;
}
