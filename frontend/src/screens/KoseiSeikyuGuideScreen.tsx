import { Card } from "../components/ui";

export function KoseiSeikyuGuideScreen() {
  return (
    <Card className="p-6 space-y-4">
      <h1 className="text-xl font-bold">更正の請求</h1>
      <p>申告済みの内容を訂正する場合は、対象年の申告書と根拠資料を確認してください。</p>
      <p>手続きの要件と期限は、国税庁または所轄税務署に確認してください。この画面は提出や還付額の確定を行いません。</p>
      <a href="https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/2026.htm" target="_blank" rel="noreferrer">国税庁の案内</a>
    </Card>
  );
}
