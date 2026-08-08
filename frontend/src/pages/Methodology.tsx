import { useLanguage } from '@/i18n/LanguageContext'

export default function Methodology() {
  const { tr } = useLanguage()
  return (
    <article className="max-w-3xl">
      <p className="text-micro uppercase tracking-wide text-ink-muted">
        {tr('Contrato epistemológico', 'Epistemic contract')}
      </p>
      <h1 className="mt-3 text-display font-semibold">{tr('Metodología', 'Methodology')}</h1>
      <p className="mt-5 text-lede text-ink-secondary">
        {tr(
          'Aleph separa entender, recuperar y evaluar. La autoridad nunca sustituye la evidencia y la insuficiencia es un resultado válido.',
          'Aleph separates understanding, retrieval and evaluation. Authority never substitutes for evidence, and insufficiency is a valid result.',
        )}
      </p>
      <div className="mt-12 space-y-12 text-body text-ink-secondary">
        <section>
          <h2 className="text-title font-semibold text-ink-primary">
            {tr('Siete fases antes del veredicto', 'Seven stages before the verdict')}
          </h2>
          <p className="mt-4">
            {tr(
              'Documento, proposiciones, grafo temático, vocabulario de búsqueda, evidencia, agrupación de noticias y preparación. Sin evidencia suficiente, no se publica una conclusión factual.',
              'Document, propositions, topic graph, search vocabulary, evidence, news clustering and preparation. Without sufficient evidence, no factual conclusion is published.',
            )}
          </p>
        </section>
        <section>
          <h2 className="text-title font-semibold text-ink-primary">{tr('Evaluación ciega', 'Blind evaluation')}</h2>
          <p className="mt-4">
            {tr(
              'El evaluador recibe la afirmación, su fecha, contexto semántico y evidencia. No recibe nombre, cargo, partido, gobierno u oposición, medio ni prestigio institucional.',
              'The evaluator receives the claim, its date, semantic context and evidence. It does not receive a name, office, party, government/opposition status, outlet or institutional prestige.',
            )}
          </p>
        </section>
        <section>
          <h2 className="text-title font-semibold text-ink-primary">
            {tr('Contexto atribuido después', 'Attributed context afterward')}
          </h2>
          <p className="mt-4">
            {tr(
              'Los perfiles de actor, patrones retóricos e intereses declarados se muestran sólo tras fijar el veredicto y nunca pueden modificarlo.',
              'Actor profiles, rhetorical patterns and declared interests are shown only after the verdict is fixed and can never modify it.',
            )}
          </p>
        </section>
        <section>
          <h2 className="text-title font-semibold text-ink-primary">{tr('Límites', 'Limitations')}</h2>
          <p className="mt-4">
            {tr(
              'La recuperación limita todo lo demás. Las pruebas de neutralidad miden invariancia ante sustituciones irrelevantes; no demuestran ausencia matemática de sesgo.',
              'Retrieval constrains everything downstream. Neutrality tests measure invariance under irrelevant substitutions; they do not prove the mathematical absence of bias.',
            )}
          </p>
        </section>
      </div>
    </article>
  )
}
