#!/usr/bin/env bash
# Sends a comprehensive QA pipeline summary to Microsoft Teams via Incoming Webhook.
#
# Required env vars:
#   TEAMS_WEBHOOK_URL  — Teams channel Incoming Webhook URL
#   JIRA_KEY           — Jira issue key
#   PIPELINE_URL       — GitHub Actions run URL
#
# Stage result env vars:
#   STAGE_PLANNER, STAGE_DESIGNER, STAGE_AUTOMATION, STAGE_EXECUTOR, STAGE_HEALER
#
# Stage detail env vars:
#   PLANNER_GAP_SCORE, DESIGNER_CASES_CREATED, DESIGNER_AUTOMATABLE,
#   AUTOMATION_SCRIPTS, AUTOMATION_BRANCH, AUTOMATION_PR_URL,
#   EXECUTOR_TOTAL, EXECUTOR_PASSED, EXECUTOR_FAILED, EXECUTOR_SKIPPED,
#   EXECUTOR_PASS_RATE, QASE_RUN_ID, QASE_PROJECT_CODE,
#   HEALER_SELF_HEALED, HEALER_DEFECTS, HEALER_DATA_CORRECTIONS

set -euo pipefail

if [ -z "${TEAMS_WEBHOOK_URL:-}" ]; then
  echo "::warning::TEAMS_WEBHOOK_URL is not set. Skipping Teams notification."
  exit 0
fi

# ── Read stage results ──
PLANNER="${STAGE_PLANNER:-skipped}"
DESIGNER="${STAGE_DESIGNER:-skipped}"
AUTOMATION="${STAGE_AUTOMATION:-skipped}"
EXECUTOR="${STAGE_EXECUTOR:-skipped}"
HEALER="${STAGE_HEALER:-skipped}"

# ── Determine overall status ──
EXEC_TOTAL="${EXECUTOR_TOTAL:-0}"
EXEC_FAILED="${EXECUTOR_FAILED:-0}"

if [ "$EXECUTOR" = "success" ] && [ "$EXEC_TOTAL" != "0" ] && [ "$EXEC_FAILED" = "0" ]; then
  OVERALL="ALL TESTS PASSED"
  THEME="good"
  HEADER_ICON="🟢"
elif [ "$EXECUTOR" = "success" ] && [ "$EXEC_TOTAL" = "0" ]; then
  OVERALL="NO TESTS EXECUTED"
  THEME="warning"
  HEADER_ICON="⚠️"
elif [ "$EXECUTOR" = "success" ] && [ "$EXEC_FAILED" != "0" ]; then
  OVERALL="TESTS COMPLETED WITH FAILURES"
  THEME="attention"
  HEADER_ICON="🟡"
elif [ "$HEALER" = "success" ] && [ "$EXEC_TOTAL" != "0" ]; then
  OVERALL="COMPLETED WITH HEALING"
  THEME="attention"
  HEADER_ICON="🔧"
elif [ "$HEALER" = "success" ] && [ "$EXEC_TOTAL" = "0" ]; then
  OVERALL="NO TESTS EXECUTED"
  THEME="warning"
  HEADER_ICON="⚠️"
elif [ "$PLANNER" = "success" ] && [ "$DESIGNER" = "skipped" ]; then
  OVERALL="STOPPED — GATE 1 (Gap Analysis)"
  THEME="warning"
  HEADER_ICON="🛑"
elif [ "$DESIGNER" = "success" ] && [ "$AUTOMATION" = "skipped" ]; then
  OVERALL="STOPPED — GATE 2 (No Automatable Cases)"
  THEME="warning"
  HEADER_ICON="🛑"
else
  OVERALL="PIPELINE FAILED"
  THEME="attention"
  HEADER_ICON="🔴"
fi

# ── Stage status emoji ──
icon() {
  case "$1" in
    success)   echo "✅";;
    failure)   echo "❌";;
    skipped)   echo "⏭️";;
    cancelled) echo "🚫";;
    *)         echo "❓";;
  esac
}

# ── Stage detail text ──
planner_detail() {
  local score="${PLANNER_GAP_SCORE:-0}"
  echo "Gap Score: ${score}/5"
}

designer_detail() {
  local cases="${DESIGNER_CASES_CREATED:-0}"
  local auto="${DESIGNER_AUTOMATABLE:-0}"
  echo "Cases: ${cases} | Automatable: ${auto}"
}

automation_detail() {
  local scripts="${AUTOMATION_SCRIPTS:-0}"
  local branch="${AUTOMATION_BRANCH:-}"
  if [ -n "$branch" ]; then
    echo "Scripts: ${scripts} | Branch: ${branch}"
  else
    echo "Scripts: ${scripts}"
  fi
}

executor_detail() {
  local total="${EXECUTOR_TOTAL:-0}"
  local passed="${EXECUTOR_PASSED:-0}"
  local failed="${EXECUTOR_FAILED:-0}"
  local rate="${EXECUTOR_PASS_RATE:-N/A}"
  local scripts="${AUTOMATION_SCRIPTS:-0}"
  if [ "$total" = "0" ]; then
    echo "⚠ No tests executed (check grep filter / test tags)"
  else
    local detail="Total: ${total} | Pass: ${passed} | Fail: ${failed} | Rate: ${rate}"
    if [ "$scripts" = "0" ] && [ "$total" != "0" ]; then
      detail="${detail} — tests from main branch (automation produced 0 scripts)"
    fi
    echo "$detail"
  fi
}

healer_detail() {
  local healed="${HEALER_SELF_HEALED:-0}"
  local defects="${HEALER_DEFECTS:-0}"
  local data="${HEALER_DATA_CORRECTIONS:-0}"
  local actions_total=$(( healed + defects + data ))
  local exec_failed="${EXECUTOR_FAILED:-0}"
  if [ "$actions_total" = "0" ] && [ "$exec_failed" != "0" ]; then
    echo "⚠ No actions taken despite ${exec_failed} failures"
  elif [ "$actions_total" = "0" ] && [ "${EXECUTOR_TOTAL:-0}" = "0" ]; then
    echo "⚠ Skipped — no test results to heal"
  else
    echo "Healed: ${healed} | Defects: ${defects} | Data Issues: ${data}"
  fi
}

P_ICON=$(icon "$PLANNER")
D_ICON=$(icon "$DESIGNER")
A_ICON=$(icon "$AUTOMATION")

if [ "$EXECUTOR" = "success" ] && [ "$EXEC_TOTAL" = "0" ]; then
  E_ICON="⚠️"
else
  E_ICON=$(icon "$EXECUTOR")
fi

HEALER_TOTAL=$(( ${HEALER_SELF_HEALED:-0} + ${HEALER_DEFECTS:-0} + ${HEALER_DATA_CORRECTIONS:-0} ))
if [ "$HEALER" = "success" ] && [ "$HEALER_TOTAL" = "0" ] && [ "$EXEC_FAILED" != "0" ]; then
  H_ICON="⚠️"
elif [ "$HEALER" = "success" ] && [ "$EXEC_TOTAL" = "0" ]; then
  H_ICON="⚠️"
else
  H_ICON=$(icon "$HEALER")
fi

P_DETAIL=$(planner_detail)
D_DETAIL=$(designer_detail)
A_DETAIL=$(automation_detail)
E_DETAIL=$(executor_detail)
H_DETAIL=$(healer_detail)

# ── Build test results section ──
TEST_RESULTS_SECTION=""
if [ "$EXECUTOR" = "success" ] || [ "$EXECUTOR" = "failure" ]; then
  TOTAL="${EXECUTOR_TOTAL:-0}"
  PASSED="${EXECUTOR_PASSED:-0}"
  FAILED="${EXECUTOR_FAILED:-0}"
  SKIPPED="${EXECUTOR_SKIPPED:-0}"
  RATE="${EXECUTOR_PASS_RATE:-N/A}"

  TEST_RESULTS_SECTION=$(cat <<EOSECTION
,
{
  "type": "TextBlock",
  "text": "Test Execution Summary",
  "weight": "Bolder",
  "size": "Medium",
  "separator": true,
  "spacing": "Medium"
},
{
  "type": "ColumnSet",
  "columns": [
    {
      "type": "Column",
      "width": "stretch",
      "items": [
        {"type": "TextBlock", "text": "Total", "weight": "Bolder", "horizontalAlignment": "Center", "size": "Small"},
        {"type": "TextBlock", "text": "${TOTAL}", "horizontalAlignment": "Center", "size": "ExtraLarge", "color": "Default"}
      ]
    },
    {
      "type": "Column",
      "width": "stretch",
      "items": [
        {"type": "TextBlock", "text": "Passed", "weight": "Bolder", "horizontalAlignment": "Center", "size": "Small"},
        {"type": "TextBlock", "text": "${PASSED}", "horizontalAlignment": "Center", "size": "ExtraLarge", "color": "Good"}
      ]
    },
    {
      "type": "Column",
      "width": "stretch",
      "items": [
        {"type": "TextBlock", "text": "Failed", "weight": "Bolder", "horizontalAlignment": "Center", "size": "Small"},
        {"type": "TextBlock", "text": "${FAILED}", "horizontalAlignment": "Center", "size": "ExtraLarge", "color": "Attention"}
      ]
    },
    {
      "type": "Column",
      "width": "stretch",
      "items": [
        {"type": "TextBlock", "text": "Skipped", "weight": "Bolder", "horizontalAlignment": "Center", "size": "Small"},
        {"type": "TextBlock", "text": "${SKIPPED}", "horizontalAlignment": "Center", "size": "ExtraLarge", "color": "Warning"}
      ]
    },
    {
      "type": "Column",
      "width": "stretch",
      "items": [
        {"type": "TextBlock", "text": "Pass Rate", "weight": "Bolder", "horizontalAlignment": "Center", "size": "Small"},
        {"type": "TextBlock", "text": "${RATE}", "horizontalAlignment": "Center", "size": "ExtraLarge", "weight": "Bolder"}
      ]
    }
  ]
}
EOSECTION
  )
fi

# ── Build Qase link section ──
LINKS_SECTION=""
RUN_ID="${QASE_RUN_ID:-}"
PROJECT="${QASE_PROJECT_CODE:-}"
PR_URL="${AUTOMATION_PR_URL:-}"

LINK_FACTS=""

if [ -n "$RUN_ID" ] && [ "$RUN_ID" != "null" ] && [ -n "$PROJECT" ]; then
  LINK_FACTS="${LINK_FACTS}{\"title\": \"Qase Test Run\", \"value\": \"[Run #${RUN_ID}](https://app.qase.io/run/${PROJECT}/dashboard/${RUN_ID})\"},"
fi

if [ -n "$PR_URL" ] && [ "$PR_URL" != "null" ] && [ "$PR_URL" != "" ]; then
  LINK_FACTS="${LINK_FACTS}{\"title\": \"Pull Request\", \"value\": \"[View PR](${PR_URL})\"},"
fi

if [ -n "$LINK_FACTS" ]; then
  LINK_FACTS="${LINK_FACTS%,}"
  LINKS_SECTION=$(cat <<EOLINKS
,
{
  "type": "TextBlock",
  "text": "Links",
  "weight": "Bolder",
  "size": "Medium",
  "separator": true,
  "spacing": "Medium"
},
{
  "type": "FactSet",
  "facts": [${LINK_FACTS}]
}
EOLINKS
  )
fi

# ── Build count mismatch warning ──
MISMATCH_SECTION=""
EXEC_TOTAL_NUM="${EXECUTOR_TOTAL:-0}"
DESIGNER_AUTO_NUM="${DESIGNER_AUTOMATABLE:-0}"
AUTOMATION_SCRIPTS_NUM="${AUTOMATION_SCRIPTS:-0}"
if [ "$EXEC_TOTAL_NUM" != "0" ] && { [ "$DESIGNER_AUTO_NUM" = "0" ] || [ "$AUTOMATION_SCRIPTS_NUM" = "0" ]; }; then
  MISMATCH_SECTION=$(cat <<EOMISMATCH
,
{
  "type": "TextBlock",
  "text": "⚠ Count mismatch: Executor ran ${EXEC_TOTAL_NUM} test(s) but Designer/Automation reported 0. Tests may be from pre-existing scripts in the repo.",
  "wrap": true,
  "color": "Warning",
  "spacing": "Small"
}
EOMISMATCH
  )
fi

# ── Build healer section ──
HEALER_SECTION=""
if [ "$HEALER" = "success" ] || [ "$HEALER" = "failure" ]; then
  HEALER_SECTION=$(cat <<EOHEALER
,
{
  "type": "TextBlock",
  "text": "Self-Healing Results",
  "weight": "Bolder",
  "size": "Medium",
  "separator": true,
  "spacing": "Medium"
},
{
  "type": "FactSet",
  "facts": [
    {"title": "Self-Healed", "value": "${HEALER_SELF_HEALED:-0}"},
    {"title": "Jira Defects Created", "value": "${HEALER_DEFECTS:-0}"},
    {"title": "Data Corrections Needed", "value": "${HEALER_DATA_CORRECTIONS:-0}"}
  ]
}
EOHEALER
  )
fi

# ── Build Adaptive Card JSON ──
CARD_JSON=$(cat <<EOCARD
{
  "type": "message",
  "attachments": [
    {
      "contentType": "application/vnd.microsoft.card.adaptive",
      "contentUrl": null,
      "content": {
        "\$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": [
          {
            "type": "TextBlock",
            "text": "${HEADER_ICON} QA E2E Pipeline — ${OVERALL}",
            "weight": "Bolder",
            "size": "Large",
            "color": "${THEME}",
            "wrap": true
          },
          {
            "type": "FactSet",
            "facts": [
              {"title": "Jira Story", "value": "${JIRA_KEY:-N/A}"},
              {"title": "Environment", "value": "${BASE_URL:-N/A}"},
              {"title": "Trigger", "value": "${GITHUB_EVENT_NAME:-manual}"},
              {"title": "Run #", "value": "${GITHUB_RUN_NUMBER:-0}"}
            ]
          },
          {
            "type": "TextBlock",
            "text": "Pipeline Stages",
            "weight": "Bolder",
            "size": "Medium",
            "separator": true,
            "spacing": "Medium"
          },
          {
            "type": "FactSet",
            "facts": [
              {"title": "${P_ICON} 1. Planner", "value": "${P_DETAIL}"},
              {"title": "${D_ICON} 2. Qase Designer", "value": "${D_DETAIL}"},
              {"title": "${A_ICON} 3. Automation", "value": "${A_DETAIL}"},
              {"title": "${E_ICON} 4. Executor", "value": "${E_DETAIL}"},
              {"title": "${H_ICON} 5. Healer", "value": "${H_DETAIL}"}
            ]
          }
          ${MISMATCH_SECTION}
          ${TEST_RESULTS_SECTION}
          ${HEALER_SECTION}
          ${LINKS_SECTION}
        ],
        "actions": [
          {
            "type": "Action.OpenUrl",
            "title": "View Pipeline Run",
            "url": "${PIPELINE_URL:-#}"
          }
        ]
      }
    }
  ]
}
EOCARD
)

# ── Send to Teams ──
echo "[Teams] Sending notification..."
HTTP_CODE=$(curl -s -o /tmp/teams-response.txt -w "%{http_code}" \
  -H "Content-Type: application/json" \
  -d "$CARD_JSON" \
  "$TEAMS_WEBHOOK_URL")

RESPONSE=$(cat /tmp/teams-response.txt)
echo "[Teams] HTTP $HTTP_CODE — $RESPONSE"

if [ "$HTTP_CODE" -ge 200 ] && [ "$HTTP_CODE" -lt 300 ]; then
  echo "Teams notification sent successfully."
else
  echo "::warning::Teams notification failed: HTTP $HTTP_CODE — $RESPONSE"
fi
