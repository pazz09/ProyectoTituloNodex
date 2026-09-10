import type { Metadata, Viewport } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'NODEX — Security Intelligence',
  description: 'Análisis multiagente de logs de seguridad para detectar anomalías e incidentes.',
  generator: 'NODEX',
}

export const viewport: Viewport = {
  colorScheme: 'light',
  themeColor: '#f6f8fb',
  userScalable: true,
}

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="es" className="bg-background">
      <body className="antialiased">
        {children}
      </body>
    </html>
  )
}
