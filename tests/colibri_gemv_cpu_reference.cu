/* Standalone diagnostic: include the pinned backend through its HIP compatibility layer.
 * Thresholds are fixed before execution; no CPU/GPU agreement assumptions. */
#include <cstdio>
#include <cstdlib>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <vector>
#include "backend_gpu_compat.h"
#include "backend_cuda.cu"

#define GPU(call) do { cudaError_t e=(call); if(e!=cudaSuccess) { fprintf(stderr,"GPU_ERROR %s: %s\n",#call,cudaGetErrorString(e)); std::exit(2); } } while(0)
static uint32_t rng=0x6d2b79f5u;
static uint32_t next_u32() { rng ^= rng<<13; rng ^= rng>>17; rng ^= rng<<5; return rng; }
static int check(int K,int N) {
    const int S=4,G=64; const float guard=-123456.75f;
    std::vector<int8_t> w((size_t)K*N);
    std::vector<float> sc(N), x((size_t)S*K), init((size_t)S*N+2*G,guard), got(init.size());
    std::vector<double> ref((size_t)S*N);
    for(auto &v:w) v=(int8_t)((int)(next_u32()%255)-127);
    for(auto &v:sc) v=0.001f+(next_u32()%100)*0.00001f;
    for(auto &v:x) v=((int)(next_u32()%65537)-32768)/32768.0f;
    for(int s=0;s<S;s++) for(int n=0;n<N;n++) {
        double sum=0; for(int k=0;k<K;k++) sum+=(double)w[(size_t)n*K+k]*(double)x[(size_t)s*K+k];
        ref[(size_t)s*N+n]=sum*(double)sc[n];
    }
    ColiCudaTensor *t=nullptr;
    if(!coli_cuda_tensor_upload(&t,w.data(),sc.data(),1,K,N,0)) { fprintf(stderr,"UPLOAD_ERROR\n"); return 1; }
    float *xd=nullptr,*base=nullptr;
    GPU(cudaMalloc(&xd,x.size()*sizeof(float))); GPU(cudaMalloc(&base,init.size()*sizeof(float)));
    GPU(cudaMemcpy(xd,x.data(),x.size()*sizeof(float),cudaMemcpyHostToDevice));
    int fails=0;
    for(int repeat=0;repeat<3;repeat++) for(int mode=0;mode<2;mode++) {
        GPU(cudaMemcpy(base,init.data(),init.size()*sizeof(float),cudaMemcpyHostToDevice));
        if(mode==0) {
            if(!coli_cuda_tensor_gemm_async(t,base+G,xd,4,nullptr)) { fprintf(stderr,"DISPATCH_ERROR\n"); std::exit(2); }
        } else for(int s=0;s<S;s++) {
            if(!coli_cuda_tensor_gemm_async(t,base+G+(size_t)s*N,xd+(size_t)s*K,1,nullptr)) { fprintf(stderr,"DISPATCH_ERROR\n"); std::exit(2); }
        }
        GPU(cudaGetLastError()); GPU(cudaDeviceSynchronize());
        GPU(cudaMemcpy(got.data(),base,got.size()*sizeof(float),cudaMemcpyDeviceToHost));
        int badguard=0; for(int i=0;i<G;i++) if(got[i]!=guard || got[G+S*N+i]!=guard) badguard++;
        for(int s=0;s<S;s++) {
            int bad=0,nan=0; double maxabs=0,maxrel=0;
            for(int n=0;n<N;n++) {
                size_t j=(size_t)s*N+n; double v=got[G+j],r=ref[j],err=std::abs(v-r);
                if(!std::isfinite(v)) { nan++; bad++; }
                else { maxabs=std::fmax(maxabs,err); maxrel=std::fmax(maxrel,err/std::fmax(std::abs(r),1e-30)); if(err>1e-3+1e-4*std::abs(r)) bad++; }
            }
            printf("RESULT K=%d N=%d repeat=%d mode=%s row=%d max_abs=%.9g max_rel=%.9g bad=%d nonfinite=%d guard=%d\n",K,N,repeat,mode?"four_NR1":"NR4_request",s,maxabs,maxrel,bad,nan,badguard);
            fails+=bad+(badguard!=0);
        }
    }
    GPU(cudaFree(xd)); GPU(cudaFree(base)); coli_cuda_tensor_free(t); return fails;
}
int main() {
    setvbuf(stdout,nullptr,_IONBF,0);
    printf("PRESET abs=1e-3 rel=1e-4 seed=0x6d2b79f5 repeats=3 SK=%s W4=%s\n",getenv("COLI_CUDA_GEMV_SK"),getenv("COLI_CUDA_GEMV_W4"));
    int devices[]={0}; if(!coli_cuda_init(devices,1)) { fprintf(stderr,"INIT_ERROR (not a skip)\n"); return 2; }
    hipDeviceProp_t p; GPU(hipGetDeviceProperties(&p,0)); printf("DEVICE %s arch=%s CU=%d warp=%d\n",p.name,p.gcnArchName,p.multiProcessorCount,p.warpSize);
    int fails=0; fails+=check(2048,300); fails+=check(2048,1100); fails+=check(10240,300);
    printf("FINAL failures=%d\n",fails); return fails?1:0;
}
