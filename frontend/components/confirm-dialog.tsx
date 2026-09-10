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
      <DialogContent className="modal" showCloseButton={false}>
        <div className="modal-icon">
          <AlertTriangle size={19} />
        </div>
        <DialogTitle className="modal-title">{titulo}</DialogTitle>
        <DialogDescription className="modal-text">{descripcion}</DialogDescription>
        <div className="modal-actions">
          <DialogClose className="btn">Cancelar</DialogClose>
          <button
            className={variante === 'danger' ? 'btn btn-danger' : 'btn btn-primary'}
            onClick={onConfirmar}
          >
            {textoConfirmar}
          </button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
