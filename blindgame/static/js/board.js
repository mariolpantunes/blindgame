// Projector board: live standings; after closing, what each problem really was.

// Projector board: live standings (names, ranks, progress). No values: each
// player sees their own results only, on their own screen.

import { api, el, standingHead, standingRows, watchBoard } from "./api.js";

const $ = (id) => document.getElementById(id);

function render(board) {
  const c = board.contest;
  document.title = `blindgame · ${c.title}`;
  $("title").textContent = c.title;
  $("status").textContent = c.status;
  $("status").className = `chip status-${c.status}`;
  $("join-url").textContent = location.host;
  $("rules").textContent =
    `${c.problems} problems, ${c.budget} evaluations each. Ranked per problem by the distance to the ` +
    "optimum (ties: fewer evaluations to reach it); the score is the sum of ranks, lower is better. " +
    "Only first attempts count.";
  $("head").replaceChildren(standingHead(board));
  $("rows").replaceChildren(...standingRows(board));
  $("empty").classList.toggle("hidden", board.standings.length > 0);
}

api("GET", "/api/board")
  .then((board) => {
    render(board);
    watchBoard(render);
  })
  .catch((e) => {
    $("error").replaceChildren(el("span", {}, e.message));
  });
