import Platform from '../platform';
export default function Page({params}:{params:{slug:string[]}}){return <Platform route={'/'+(params.slug||[]).join('/')}/>}
