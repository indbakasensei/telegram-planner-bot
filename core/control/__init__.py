"""
core/control -- v15.3 M5 -- the Manual Control Plane.

"BAKA can be reliably controlled and repaired manually, using the same
underlying tool/domain capabilities that AI uses."

Layering (binding, owner directive):

    AI Worker
      → Manual Control Plane (this package)
        → Telegram commands (/control + `ctl:` callbacks)
          → ToolRegistry (core/ai/tool_adapters.build_tool_registry)
            → Domain services (EntityEngine / WorkspaceGroups /
               TelegramProjection)
              → DB / Telegram projection

Two hard rules shape every module here:

  1. NO second business-logic layer. The control plane never writes the DB
     or Telegram directly; every mutation executes through the SAME
     ToolRegistry tools the AI Worker uses. Page renderers only READ domain
     state (EntityEngine / bindings) for display -- never a write.
  2. ONE shared confirmation flow (M5-F). Every destructive / data-entry
     action goes through `core.control.actions` -- wording comes from the
     tool spec's `confirmation_message`, execution is registry.execute,
     and there is no per-feature confirmation logic.

Modules:
  * registry.py  -- ControlContext + the execution seam (registry + execute).
  * pages.py     -- pure (text, keyboard) page renderers, offline-testable.
  * actions.py   -- the single confirm/preview flow + pending store.
  * router.py    -- /control entry, `ctl:` callback router, gather data entry.
"""
