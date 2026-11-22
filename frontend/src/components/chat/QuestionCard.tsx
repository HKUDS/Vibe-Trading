import { useTranslation } from "react-i18next";
import { useState, type FC } from "react";
export const QuestionCard: FC<{ questionId: string; prompt: string; options: string[]; allowFreeText?: boolean; onAnswer: (answer: string) => void }> = ({ prompt, options, allowFreeText = true, onAnswer }) => {
  const { t } = useTranslation();
  const [value, setValue] = useState("");
  return <div className="rounded-lg border border-sky-200 bg-sky-50/60 p-4 space-y-3"><p className="font-medium">{prompt}</p><div className="flex flex-wrap gap-2">{options.map((option) => <button key={option} type="button" className="rounded-md border px-3 py-1.5 hover:bg-white" onClick={() => onAnswer(option)}>{option}</button>)}</div>{allowFreeText && <form className="flex gap-2" onSubmit={(event) => { event.preventDefault(); if (value.trim()) onAnswer(value.trim()); }}><input className="min-w-0 flex-1 rounded-md border px-2 py-1.5" value={value} onChange={(event) => setValue(event.target.value)} aria-label={t("agent.answerPlaceholder")} placeholder={t("agent.answerPlaceholder")} /><button className="rounded-md bg-sky-600 px-3 py-1.5 text-white" type="submit">{t("agent.send")}</button></form>}</div>;
};
