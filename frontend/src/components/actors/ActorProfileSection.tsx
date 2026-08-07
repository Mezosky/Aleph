import type { ActorProfile, Claim } from '@/types/aleph'

const VERDICT_LABELS: Record<string, string> = {
  supported: 'respaldadas',
  partially_supported: 'parcialmente respaldadas',
  unsupported: 'sin respaldo',
  contradicted: 'contradichas',
  unverifiable: 'no verificables',
  not_a_factual_claim: 'no factuales',
  forecast_conditional: 'proyecciones condicionales',
}

interface Props {
  profiles: ActorProfile[]
  claims: Claim[]
}

export default function ActorProfileSection({ profiles, claims }: Props) {
  if (profiles.length === 0) return null
  const knownClaims = new Set(claims.map((claim) => claim.id))

  return (
    <section aria-labelledby="actor-profiles-heading" className="mt-16 border-t-2 border-line-strong pt-8">
      <div className="max-w-prose">
        <p className="text-micro font-semibold uppercase tracking-wide text-ink-muted">
          Etapa atribuida · separada del veredicto
        </p>
        <h2 id="actor-profiles-heading" className="mt-2 text-title font-semibold text-ink-primary">
          Contexto de quienes intervienen
        </h2>
        <p className="mt-3 text-body text-ink-secondary">
          Estos perfiles se ensamblan después de fijar el veredicto ciego. Oficios, intereses o
          antecedentes judiciales aportan contexto para leer el discurso; nunca hacen verdadera o
          falsa una afirmación.
        </p>
      </div>

      <div className="mt-8 grid gap-5 lg:grid-cols-2">
        {profiles.map((profile) => {
          const track = profile.claim_track_record
          return (
            <article key={profile.id} className="border border-line-hairline bg-surface-card p-5 sm:p-6">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h3 className="text-lede font-semibold text-ink-primary">{profile.display_name}</h3>
                  <p className="mt-1 text-caption text-ink-muted">
                    {profile.roles.map((role) => role.title).join(' · ')}
                  </p>
                </div>
                <span className="rounded-data border border-line-strong px-2 py-1 text-micro uppercase tracking-wide text-ink-secondary">
                  No usado en evaluación ciega
                </span>
              </div>

              {track && (
                <div className="mt-6 border-l-2 border-line-strong pl-4">
                  <p className="text-caption font-semibold text-ink-primary">
                    De {track.sample_size} afirmaciones evaluadas a ciegas
                  </p>
                  <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-caption text-ink-secondary">
                    {Object.entries(track.by_verdict).map(([verdict, count]) => (
                      <li key={verdict} className="tabular">
                        {count} {VERDICT_LABELS[verdict] ?? verdict}
                      </li>
                    ))}
                  </ul>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {track.evaluated_claim_ids.filter((id) => knownClaims.has(id)).map((id) => (
                      <a key={id} href={`#${id}`} className="text-micro text-ink-secondary underline underline-offset-2 hover:text-ink-primary">
                        {id}
                      </a>
                    ))}
                  </div>
                  <p className="mt-3 text-micro leading-relaxed text-ink-muted">{track.caveat}</p>
                </div>
              )}

              {(profile.declared_interests?.length ?? 0) > 0 && (
                <div className="mt-6">
                  <h4 className="text-caption font-semibold text-ink-primary">Intereses declarados</h4>
                  <ul className="mt-2 space-y-3 text-caption text-ink-secondary">
                    {profile.declared_interests?.map((interest, index) => (
                      <li key={`${interest.description}-${index}`}>
                        <p>{interest.description}</p>
                        <p className="mt-1 text-ink-muted">Relevancia: {interest.relevance_to_document}</p>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {(profile.legal_record?.length ?? 0) > 0 && (
                <div className="mt-6 border-t border-line-hairline pt-5">
                  <h4 className="text-caption font-semibold text-ink-primary">Registro judicial oficial</h4>
                  <ul className="mt-2 space-y-4">
                    {profile.legal_record?.map((entry, index) => (
                      <li key={`${entry.summary}-${index}`} className="text-caption text-ink-secondary">
                        <p><span className="font-semibold text-ink-primary">{entry.status}</span> · {entry.body}</p>
                        <p className="mt-1">{entry.summary}</p>
                        {entry.presumption_note && <p className="mt-2 border-l-2 border-status-warning pl-3 text-ink-primary">{entry.presumption_note}</p>}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </article>
          )
        })}
      </div>
    </section>
  )
}
