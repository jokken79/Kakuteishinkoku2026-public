import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { OnboardingScreen } from "./OnboardingScreen";

const state = vi.hoisted(() => ({ hasTaxpayer: false, mutate: vi.fn() }));
vi.mock("../lib/hooks", () => ({
  useCompleteOnboarding: () => ({ mutate: state.mutate, isPending: false, isError: false }),
  useOnboardingStatus: () => ({ data: { has_taxpayer: state.hasTaxpayer } }),
  useActiveYear: () => 2026,
}));

afterEach(() => { state.hasTaxpayer = false; state.mutate.mockClear(); vi.restoreAllMocks(); });

it("exige seleccionar expresamente la modalidad antes de continuar", async () => {
  render(<OnboardingScreen />);
  fireEvent.click(screen.getByRole("button", { name: /はじめる/ }));
  fireEvent.click(await screen.findByRole("button", { name: /次へ/ }));
  await screen.findByText("申告の種類を選んでください");
  expect(screen.getByRole("button", { name: /次へ/ })).toBeDisabled();
  expect(screen.getAllByRole("button", { pressed: false }).length).toBeGreaterThanOrEqual(4);
  fireEvent.click(screen.getByRole("button", { name: /白色申告/ }));
  expect(screen.getByRole("button", { name: /次へ/ })).toBeEnabled();
});

it("no guarda un perfil existente si se cancela la confirmación", async () => {
  state.hasTaxpayer = true;
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  render(<OnboardingScreen />);
  fireEvent.click(screen.getByRole("button", { name: /はじめる/ }));
  await screen.findByText("スペイン語の説明を表示しますか？");
  fireEvent.click(screen.getByRole("button", { name: /次へ/ }));
  await screen.findByText("申告の種類を選んでください");
  fireEvent.click(screen.getByRole("button", { name: /白色申告/ }));
  fireEvent.click(screen.getByRole("button", { name: /次へ/ }));
  for (const heading of ["消費税はどちらですか？", "提出先の税務署を選んでください", "あなたの情報を入力してください", "今年の収入を入力してください"]) {
    await screen.findByText(heading);
    if (heading === "消費税はどちらですか？") {
      expect(screen.getByRole("button", { name: /次へ/ })).toBeDisabled();
      fireEvent.click(screen.getByRole("button", { name: /^免税事業者/ }));
    }
    fireEvent.click(screen.getByRole("button", { name: /次へ/ }));
  }
  await screen.findByText("設定の確認");
  fireEvent.click(screen.getByRole("button", { name: "完了" }));
  expect(confirm).toHaveBeenCalledWith(expect.stringContaining("copia de seguridad"));
  expect(state.mutate).not.toHaveBeenCalled();
});

it("envía cero explícito y omite los ingresos que quedaron vacíos", async () => {
  render(<OnboardingScreen />);
  fireEvent.click(screen.getByRole("button", { name: /はじめる/ }));
  await screen.findByText("スペイン語の説明を表示しますか？");
  fireEvent.click(screen.getByRole("button", { name: /次へ/ }));
  await screen.findByText("申告の種類を選んでください");
  fireEvent.click(screen.getByRole("button", { name: /白色申告/ }));
  fireEvent.click(screen.getByRole("button", { name: /次へ/ }));
  for (const heading of ["消費税はどちらですか？", "提出先の税務署を選んでください", "あなたの情報を入力してください"]) {
    await screen.findByText(heading);
    if (heading === "消費税はどちらですか？") {
      fireEvent.click(screen.getByRole("button", { name: /^免税事業者/ }));
    }
    fireEvent.click(screen.getByRole("button", { name: /次へ/ }));
  }
  await screen.findByText("今年の収入を入力してください");
  fireEvent.change(screen.getByLabelText(/事業の売上（年間）/), { target: { value: "0" } });
  fireEvent.change(screen.getByLabelText(/源泉徴収税額（源泉徴収票から）/), { target: { value: "0" } });
  fireEvent.click(screen.getByRole("button", { name: /次へ/ }));
  await screen.findByText("設定の確認");
  fireEvent.click(screen.getByRole("button", { name: "完了" }));
  expect(state.mutate).toHaveBeenCalledWith(expect.objectContaining({
    incomes: [{ income_type: "jigyo", gross: 0 }, { income_type: "kyuyo", withholding: 0 }],
    filing_office: undefined,
  }), expect.any(Object));
});
