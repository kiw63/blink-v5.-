import type {Metadata,Viewport} from 'next';
import './globals.css';
export const metadata:Metadata={title:'BLINK — Every Moment, Extraordinary.',description:'BLINK AI Photo & Video Studio — foto dan video dengan pemrosesan AI asli.',icons:{icon:'/blink-logo.png'}};
export const viewport:Viewport={themeColor:'#080910',width:'device-width',initialScale:1};
export default function RootLayout({children}:{children:React.ReactNode}){return <html lang="id"><body>{children}</body></html>}
