import { api } from "../api.js";
const { ref, onMounted } = Vue;
export const EnvsView = {
  setup() {
    const items = ref([]); const err = ref("");
    async function reload() {
      try { items.value = (await api("/api/envs")).items || []; }
      catch (e) { err.value = e.message || String(e); }
    }
    onMounted(reload);
    return { items, err, reload };
  },
  template: `
  <div class="panel">
    <h2>环境</h2>
    <p class="hint">风险等级越高，发布与熔断越敏感；生产级环境由生产闸接管：禁一键全量，全量意图只进影子全量草案，二次确认或分步爬坡后求值才全开。</p>
    <div class="err" v-if="err">{{ err }}</div>
    <table>
      <thead><tr><th>代码</th><th>名称</th><th>风险等级</th><th>生产闸</th><th>全量策略</th></tr></thead>
      <tbody>
        <tr v-for="it in items" :key="it.id">
          <td>{{ it.code }}</td><td>{{ it.title }}</td><td>{{ it.risk_level }}</td>
          <td><span class="pill danger" v-if="it.prod_gate">禁一键全量</span><span class="muted" v-else>—</span></td>
          <td>{{ it.full_policy }}</td>
        </tr>
      </tbody>
    </table>
  </div>`
};
