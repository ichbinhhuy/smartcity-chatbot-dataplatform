// cube.js -- Cấu hình Cube.js Semantic Layer
// Row-Level Security (RLS): Tự động lọc dữ liệu dựa trên Security Context (section_id) trong JWT payload

module.exports = {
  queryRewrite: (query, { securityContext }) => {
    if (securityContext && securityContext.section_id) {
      query.filters = query.filters || [];
      query.filters.push({
        member: 'districts.id',
        operator: 'equals',
        values: [securityContext.section_id],
      });
    }
    return query;
  },
};
