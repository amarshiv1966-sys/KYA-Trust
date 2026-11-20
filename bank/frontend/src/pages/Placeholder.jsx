// Pages that later steps build (mandate in K8, shop in K10).
export default function Placeholder({ page, step }) {
  return (
    <div data-kya-page={page}>
      <div className="card"><h2>Coming soon</h2><p>This page is built in step {step}.</p></div>
    </div>
  )
}
