'use client'

import { AlertTriangle } from 'lucide-react'

import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from '@/components/ui/dialog'

/**
 * Confirmación para una acción que no es reversible desde la interfaz.
 *
 * Usa el primitivo de shadcn solo por el comportamiento (portal, foco
 * atrapado, Escape); el aspecto lo dan las clases de `globals.css`, porque
 * las utilidades por defecto del componente traen tokens (`bg-popover`,
 * `text-destructive`) que este diseño no define y se verían fuera de lugar.
 */
export function ConfirmDialog({
  abierto,
  titulo,
  descripcion,
  textoConfirmar,
  variante = 'primary',
  onConfirmar,
  onCancelar,
}: {
  abierto: boolean
  titulo: string
  descripcion: string
  textoConfirmar: string
  variante?: 'primary' | 'danger'
  onConfirmar: () => void
  onCancelar: () => void
}) {
  return (
    <Dialog open={abierto} onOpenChange={(open) => !open && onCancelar()}>
      <DialogContent className="confirm-modal" showCloseButton={false}>
        <div className="confirm-icon">
          <AlertTriangle size={19} />
        </div>
        <DialogTitle className="confirm-title">{titulo}</DialogTitle>
        <DialogDescription className="confirm-text">{descripcion}</DialogDescription>
        <div className="confirm-actions">
          <DialogClose className="secondary-button">Cancelar</DialogClose>
          <button
            className={variante === 'danger' ? 'danger-button' : 'primary-button'}
            onClick={onConfirmar}
          >
            {textoConfirmar}
          </button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
