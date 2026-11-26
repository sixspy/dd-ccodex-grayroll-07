import { api } from "../api.js";
const { ref, onMounted } = Vue;
export const CompareView = {
  setup() {
    const flagId = ref(1); const envId = ref(3);
    const detail = ref(null); const matrix = ref(null); const err = ref("");
    async function reload() {
      err.value = "";
      try {
        detail.value = await api(`/api/compare/flag/${flagId.value}/env/${envId.value}`);
        matrix.value = await api("/api/compare/matrix");
      } catch (e) { err.value = e.message || String(e); }
    }
    function fmt(ts) { return ts ? new Date(ts * 1000).toLocaleString() : ""; }
    onMounted(reload);
    return { flagId, envId, detail, matrix, err, reload, fmt };
  },
  template: `
  <div class="grid">
    <div class="panel span-5">
      <h2>正式 vs 影子</h2>
      <div class="field"><label>开关ID</label><input type="number" v-model.number="flagId" /></div>
      <div class="field"><label>环境ID</label><input type="number" v-model.number="envId" /></div>
      <button class="btn secondary" @click="reload">对比</button>
      <div class="err" v-if="err">{{ err }}</div>
      <template v-if="detail">
        <div v-if="detail.official_full_gate" style="margin-top:0.8rem">
          <h2>全量闸</h2>
          <p v-if="detail.official_full_gate.granted" class="pill">已放行（v{{ detail.official_full_gate.version }} 有放行账）</p>
          <p v-else class="pill danger">未确认全量·求值阻断中（v{{ detail.official_full_gate.version }} 无放行账）</p>
        </div>
        <div style="margin-top:0.8rem">
          <h2>确认记录</h2>
          <table v-if="detail.confirm_records.length">
            <thead><tr><th>时间</th><th>确认人</th><th>说明</th></tr></thead>
            <tbody><tr v-for="c in detail.confirm_records" :key="'c'+c.id">
              <td>{{ fmt(c.created_at) }}</td><td>{{ c.actor }}</td><td>{{ c.detail }}</td>
            </tr></tbody>
          </table>
          <p v-else class="muted">无二次确认记录</p>
          <h2 style="margin-top:0.8rem">分步记录</h2>
          <table v-if="detail.step_records.length">
            <thead><tr><th>时间</th><th>操作人</th><th>说明</th></tr></thead>
            <tbody><tr v-for="s in detail.step_records" :key="'s'+s.id">
              <td>{{ fmt(s.created_at) }}</td><td>{{ s.actor }}</td><td>{{ s.detail }}</td>
            </tr></tbody>
          </table>
          <p v-else class="muted">无分步爬坡记录</p>
          <h2 style="margin-top:0.8rem">全量放行账</h2>
          <table v-if="detail.full_open_grants.length">
            <thead><tr><th>版本</th><th>来源</th><th>放行人</th><th>时间</th></tr></thead>
            <tbody><tr v-for="g in detail.full_open_grants" :key="'g'+g.id">
              <td>v{{ g.version }}</td><td>{{ g.source }}</td><td>{{ g.granted_by }}</td><td>{{ fmt(g.granted_at) }}</td>
            </tr></tbody>
          </table>
          <p v-else class="muted">无放行账</p>
        </div>
        <pre style="margin-top:0.8rem">{{ detail }}</pre>
      </template>
    </div>
    <div class="panel span-7">
      <h2>环境矩阵</h2>
      <div v-if="matrix">
        <table>
          <thead>
            <tr>
              <th>开关</th>
              <th v-for="e in matrix.envs" :key="e.id">{{ e.code }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in matrix.matrix" :key="row.flag_id">
              <td>{{ row.flag_key }}</td>
              <td v-for="c in row.cells" :key="c.env_id">
                <span v-if="c.has_rule">{{ c.percent }}% v{{ c.version }}</span>
                <span v-else class="muted">—</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>`
};
