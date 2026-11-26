import { api } from "../api.js";
const { ref, onMounted } = Vue;
export const EvaluateView = {
  setup() {
    const form = ref({ flag_key: "checkout.new_pay", env_code: "prod", subject_key: "u-1001" });
    const result = ref(null); const board = ref(null); const err = ref("");
    async function reloadBoard() { board.value = await api("/api/evaluate/board"); }
    async function run() {
      err.value = "";
      try { result.value = await api("/api/evaluate", { method: "POST", body: JSON.stringify(form.value) }); }
      catch (e) { err.value = e.message || String(e); }
    }
    onMounted(reloadBoard);
    return { form, result, board, err, run, reloadBoard };
  },
  template: `
  <div class="grid">
    <div class="panel span-5">
      <h2>在线求值</h2>
      <p class="hint">生产级环境的百分百规则须有全量放行账（二次确认或分步爬坡）才放开；未确认的全量一律不命中。</p>
      <div class="field"><label>开关键</label><input v-model="form.flag_key" /></div>
      <div class="field"><label>环境</label>
        <select v-model="form.env_code"><option>dev</option><option>staging</option><option>prod</option></select>
      </div>
      <div class="field"><label>主体键</label><input v-model="form.subject_key" /></div>
      <button class="btn" @click="run">求值</button>
      <div class="err" v-if="err">{{ err }}</div>
      <div class="err" v-if="result && result.reason==='prod_full_unconfirmed'">
        未确认的全量规则：求值不放开（须二次确认或分步爬坡后才全开）。
      </div>
      <pre v-if="result" style="margin-top:0.8rem">{{ result }}</pre>
    </div>
    <div class="panel span-7">
      <h2>正式规则板</h2>
      <table v-if="board">
        <thead><tr><th>开关</th><th>环境</th><th>类型</th><th>%</th><th>版本</th><th>全量</th></tr></thead>
        <tbody>
          <tr v-for="(r,i) in board.rules" :key="i">
            <td>{{ r.flag_key }}</td><td>{{ r.env_code }}</td><td>{{ r.kind }}</td><td>{{ r.percent }}</td><td>v{{ r.version }}</td>
            <td>
              <template v-if="r.percent >= 100">
                <span class="pill" v-if="r.full_open">全开·有放行账</span>
                <span class="pill danger" v-else>未确认·阻断</span>
              </template>
              <span class="muted" v-else>—</span>
            </td>
          </tr>
        </tbody>
      </table>
      <button class="btn secondary" style="margin-top:0.7rem" @click="reloadBoard">刷新</button>
    </div>
  </div>`
};
