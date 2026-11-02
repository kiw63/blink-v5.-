/** @type {import('next').NextConfig} */
const nextConfig={
  reactStrictMode:true,
  poweredByHeader:false,
  async rewrites(){return [{source:'/api/:path*',destination:`${process.env.BACKEND_URL||'http://127.0.0.1:8000'}/api/:path*`}]},
  async headers(){return [{source:'/(.*)',headers:[{key:'X-Content-Type-Options',value:'nosniff'},{key:'Referrer-Policy',value:'strict-origin-when-cross-origin'},{key:'X-Frame-Options',value:'DENY'}]}]}
}
module.exports=nextConfig
