"use client";

import AutoAwesomeIcon from "@mui/icons-material/AutoAwesome";
import CloseIcon from "@mui/icons-material/Close";
import SendIcon from "@mui/icons-material/Send";
import SmartToyIcon from "@mui/icons-material/SmartToy";
import {
  Alert,
  Box,
  Button,
  Chip,
  Fab,
  IconButton,
  TextField,
  Tooltip,
  Typography
} from "@mui/material";
import { useMemo, useState } from "react";
import { askCopilot } from "../lib/api";
import type { CopilotFilters, CopilotResponse } from "../lib/types";

type AnalystCopilotProps = {
  activeTab: string;
  selectedCellId: string | null;
  filters: CopilotFilters;
};

const QUICK_PROMPTS = [
  {
    label: "Selected hotspot",
    mode: "selected_hotspot",
    question: "Explain the selected hotspot and why it should be considered."
  },
  {
    label: "Deployment priority",
    mode: "deployment_priority",
    question: "Why deploy enforcement here first based on the current dashboard data?"
  },
  {
    label: "Forecast",
    mode: "forecast",
    question: "Summarize the forecast signals for the current dashboard view."
  },
  {
    label: "Judge pitch",
    mode: "judge_pitch",
    question: "Give me a concise judge pitch for ParkWatch."
  },
  {
    label: "Limitations",
    mode: "limitations",
    question: "What are the most important limitations and safe claim boundaries?"
  }
];

export function AnalystCopilot({ activeTab, selectedCellId, filters }: AnalystCopilotProps) {
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [response, setResponse] = useState<CopilotResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const statusLabel = useMemo(() => {
    if (!response) return "Ready";
    if (response.provider === "hf") return response.cached ? "HF cached" : "HF live";
    return response.cached ? "Fallback cached" : "Local fallback";
  }, [response]);

  const submitQuestion = async (nextQuestion = question, mode = "freeform") => {
    const trimmed = nextQuestion.trim();
    if (!trimmed || loading) return;

    setLoading(true);
    setError(null);
    setQuestion(trimmed);
    try {
      const result = await askCopilot({
        question: trimmed,
        mode,
        active_tab: activeTab,
        selected_cell_id: selectedCellId,
        filters
      });
      setResponse(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Copilot request failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      {!open && (
        <Tooltip title="Ask ParkWatch Analyst">
          <Fab
            color="primary"
            aria-label="Open ParkWatch analyst copilot"
            onClick={() => setOpen(true)}
            sx={{
              position: "fixed",
              right: { xs: 18, md: 28 },
              bottom: { xs: 18, md: 28 },
              zIndex: 50,
              borderRadius: 2
            }}
          >
            <SmartToyIcon />
          </Fab>
        </Tooltip>
      )}

      {open && (
        <Box
          className="copilot-panel"
          role="dialog"
          aria-label="ParkWatch Analyst Copilot"
        >
          <Box className="copilot-header">
            <Box>
              <Typography className="eyebrow" component="p">
                Analyst copilot
              </Typography>
              <Typography variant="h6" component="h2">
                Ask ParkWatch
              </Typography>
            </Box>
            <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
              <Chip
                size="small"
                color={response?.provider === "hf" ? "success" : "default"}
                label={statusLabel}
              />
              <Tooltip title="Close">
                <IconButton aria-label="Close copilot" onClick={() => setOpen(false)}>
                  <CloseIcon />
                </IconButton>
              </Tooltip>
            </Box>
          </Box>

          <Typography className="muted" variant="body2">
            Answers use the current ParkWatch data context and stay within proxy-safe
            wording.
          </Typography>

          <Box sx={{ display: "flex", flexWrap: "wrap", gap: 1 }}>
            {QUICK_PROMPTS.map((prompt) => (
              <Chip
                key={prompt.mode}
                icon={<AutoAwesomeIcon />}
                label={prompt.label}
                clickable
                disabled={loading}
                onClick={() => submitQuestion(prompt.question, prompt.mode)}
              />
            ))}
          </Box>

          <Box sx={{ display: "flex", alignItems: "flex-start", gap: 1 }}>
            <TextField
              fullWidth
              multiline
              minRows={2}
              maxRows={4}
              size="small"
              label="Ask a question"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              onKeyDown={(event) => {
                if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
                  submitQuestion();
                }
              }}
            />
            <Tooltip title="Send">
              <span>
                <Button
                  aria-label="Send copilot question"
                  variant="contained"
                  disabled={loading || !question.trim()}
                  onClick={() => submitQuestion()}
                  sx={{ minWidth: 46, height: 40, px: 1.2 }}
                >
                  <SendIcon fontSize="small" />
                </Button>
              </span>
            </Tooltip>
          </Box>

          {error && <Alert severity="error">{error}</Alert>}

          <Box className="copilot-answer">
            {loading && <Typography className="muted">Reading the graph context...</Typography>}
            {!loading && response && (
              <>
                <Typography component="pre">{response.answer}</Typography>
                <Box className="copilot-evidence">
                  {response.evidence.slice(0, 4).map((item) => (
                    <span key={item.label}>
                      <strong>{item.label}</strong>
                      {item.value}
                    </span>
                  ))}
                </Box>
                {response.warnings.map((warning) => (
                  <Typography className="muted" key={warning} variant="caption">
                    {warning}
                  </Typography>
                ))}
              </>
            )}
            {!loading && !response && (
              <Typography className="muted">
                Pick a prompt or ask about the selected hotspot, forecast, deployment
                priority, or limitations.
              </Typography>
            )}
          </Box>
        </Box>
      )}
    </>
  );
}
