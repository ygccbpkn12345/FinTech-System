function stringValue(value) {
  return value == null ? '' : String(value)
}

export function normalizeReflectionExtraFields(source = {}) {
  const rawRoles = source.roleReflections ?? source.role_reflections
  return {
    fullText: stringValue(source.fullText ?? source.full_text),
    routerReflection: stringValue(source.routerReflection ?? source.router_reflection),
    weeklySummary: stringValue(source.weeklySummary ?? source.weekly_summary),
    roleReflections: Array.isArray(rawRoles)
      ? rawRoles
          .map((item) => ({
            role: stringValue(item?.role ?? item?.name),
            content: stringValue(item?.content ?? item?.text),
          }))
          .filter((item) => item.role || item.content)
      : [],
  }
}
