
import torch
import matplotlib.pyplot as plt
import numpy as np
import torch
import torch.nn as nn # 인공 신경망 모델들 모아놓은 모듈
import torch.nn.functional as F #그중 자주 쓰이는것들을 F로
from torchvision import transforms, datasets
import cv2
from torchvision import transforms, datasets
import pandas as pd
import os
from glob import glob
import torchvision.models as models
import sys

p = os.path.abspath('../..') # 상위 폴더를 사용하기 위해서.
sys.path.insert(1, p)
from pytorchtools.pytorchtools import EarlyStopping # 상위 폴더에 추가된 모듈.


if torch.cuda.is_available():
    DEVICE = torch.device('cuda')
else:
    DEVICE = torch.device('cpu')
#DEVICE = torch.device('cpu')
print('Using Pytorch version : ',torch.__version__,' Device : ',DEVICE)


# In[17]:


import torchaudio
#import torchaudio.functional as F
import torchaudio.transforms as T


# In[18]:


import wandb

#default param
run_config = dict(
    sr=50000,
    n_mfcc=13,
    dct_type=2, # type2 default
    lifter =0,

    
    #mel spectro
    n_mels=128,
    hop_length=300,
    n_fft =1250,    
    win_length=1250,
    f_max=25000,
    
    # training
    batch_size=32,
    mel_scale ='htk',
    
    # data
    fold=1,
)


# In[4]:





sweep_config = {
    "project" : "SVD-mfcc-hyp",
    "name": "HyperParam for MFCC",
    "method": "random",
    "parameters": {
        "sr":{
            "values":[16000,32000,50000]
        },
        "n_mfcc":{
          "values":  np.arange(13,42,1).tolist()
        },
        "lifter":{
            "values":np.arange(0,42,1).tolist()
        },
      "n_mels" :{
           "values":np.arange(30,192,10).tolist()
       },
      "n_fft": {
            "values": np.arange(256,20000,100).tolist() # 제일 중요한 파라미터
        },
      "win_length": {
            "values": np.arange(200,2051,50).tolist()
        },
       "hop_length": {
          "values": np.arange(50,850,50).tolist()
      },
       "f_max":{
          "values":np.arange(4000,25000,500).tolist()
      },
        "batch_size":{
            "values" : [8,16,32,64,128]
        },
        "mel_scale":{
            "values":['htk','slaney']
        },
      "fold":{
          "values" : [1, ]
      }
    }
}

sweep_id = wandb.sweep(sweep_config,project="SVD-mfcc-hyp",entity="bub3690")




# # SVD 문장 데이터에서 Feature 추출
# - mfcc

# In[5]:


import numpy as np
import librosa, librosa.display 
import matplotlib.pyplot as plt
#window sizde : FFT를 할때 참조할 그래프 길이 ( 프레임 하나당 sample 수 )
#자연어 처리에서는 25ms 사용. https://ahnjg.tistory.com/93
#초당 50000hz 중 1250개씩 윈도우 사이즈로 사용.
#sr=16000
#win_length =  np.int64(sr/40) # 1250
#n_fft= win_length # WINDOWS SIZE중 사용할 길이. WINDOW SIZE가 넘어가면 나머지 것들은 zero padding
#hop_length= np.int64( np.ceil(win_length/4) ) #  얼마만큼 시간 주기(sample)를 이동하면서 분석을 할 것인지. 일반적으로 window size의 1/4
#또는 10ms만큼으로 한다고 한다.
#hop_length가 mfcc의 frame수를 결정한다.


# # 데이터 나누기 - Stratified KFold
# 
# - pathology : 1194 / healthy : 634 / 총 1828
# - k = 5

# ## 1. test/ train 나누기
# 

# In[19]:


#1. train, test 나누기

import os
from glob import glob
from sklearn.model_selection import StratifiedKFold
from imblearn.over_sampling import RandomOverSampler
from collections import Counter
from sklearn.model_selection import train_test_split # train , test 분리에 사용.


pathology = glob('D:/project/voice_pathology_ai/voice_data/organics/pathology/phrase/*.wav')
healthy = glob('D:/project/voice_pathology_ai/voice_data/organics/healthy/phrase/*.wav')
print("Pathology : ",len(pathology))
print("Healthy: ",len(healthy))

pathology= [ path.split("\\")[-1] for path in pathology] # path 데이터 변환.
healthy= [ path.split("\\")[-1] for path in healthy] # path 데이터 변환.
 # path 데이터 변환 #외부데이터로 가져오기위해서, 번호만 남긴다

    
X = pathology+healthy # path 데이터 합
print("총 데이터수 : ",len(X))
Y = [] # 라벨
for idx,x in enumerate(X):
    if idx<597:
        Y.append("pathology")
    else:
        Y.append("healthy")

X, X_test, Y, Y_test = train_test_split(X, Y, test_size=0.2, shuffle=True, stratify=Y, random_state=456)
#stratify를 넣어서, test에도 라벨별 잘 분류되게 한다.

print("---")
print("훈련 셋 : ",len(Y),Counter(Y))
print("테스트 셋 : ",len(Y_test),Counter(Y_test))
print("---")


# ## 2. stratified k-fold

# In[20]:


#1. train, test 나누기
#stratified kfold
import os
import random #데이터 shuffle 사용
from glob import glob
from sklearn.model_selection import StratifiedKFold
from imblearn.over_sampling import RandomOverSampler
from collections import Counter



skf_iris = StratifiedKFold(n_splits=5,shuffle=True,random_state=456)
cnt_iter = 0

X_train_list = [] #데이터 셋 보관
Y_train_list = []

X_valid_list = []
Y_valid_list = []

for train_idx, test_idx in skf_iris.split(X,Y):
    
    #split으로 반환된 인덱스를 이용하여, 학습 검증용 테스트 데이터 추출
    cnt_iter += 1
    X_train, X_valid = [X[idx] for idx in train_idx.tolist() ], [X[idx] for idx in test_idx.tolist() ]
    Y_train, Y_valid = [Y[idx] for idx in train_idx.tolist() ], [Y[idx] for idx in test_idx.tolist() ]
    
    X_train_list.append(X_train)
    X_valid_list.append(X_valid)
    
    Y_train_list.append(Y_train)
    Y_valid_list.append(Y_valid)
    
    
    #학습 및 예측
    
    label_train = Y_train
    label_test = Y_valid
    unique_train, train_counts = np.unique(label_train, return_counts = True)
    unique_test, test_counts = np.unique(label_test, return_counts = True)
    
    uniq_cnt_train = dict(zip(unique_train, train_counts))
    uniq_cnt_test = dict(zip(unique_test, test_counts))
    
    
    
    print('교차 검증 : {}'.format(cnt_iter))
    print('학습 레이블 데이터 분포 : \n', uniq_cnt_train)
    print('검증 레이블 데이터 분포 : \n', uniq_cnt_test,'\n')


# ## 3. random over sampling

# In[21]:


#2. random over sampling
for i in range(5):
    X_temp = np.array(X_train_list[i]).reshape(-1,1)#각 데이터를 다 행으로 넣음. (1194,1)
    #Y = np.array(Y)
    ros = RandomOverSampler(random_state = 123)
    X_res,Y_res = ros.fit_resample(X_temp,Y_train_list[i])
    
    print("\n fold{} ".format(i))
    print('before dataset shape {}'.format(Counter(Y_train_list[i])) )
    print('Resampled dataset shape {}'.format(Counter(Y_res)) )   
    
    #원래대로 돌리기
    X_res=X_res.reshape(1, -1)
    X_train_list[i]=X_res[0].tolist()
    Y_train_list[i]=Y_res



# In[22]:


import pickle

#16000 load
with open("D:/project/voice_pathology_ai/voice_data/organics/phrase_sig_dict.pickle","rb") as fr:
    phrase_dict_16000 = pickle.load(fr)

#32000 load
with open("D:/project/voice_pathology_ai/voice_data/organics/phrase_sig_dict_32000.pickle","rb") as fr:
    phrase_dict_32000 = pickle.load(fr)    

#50000 load
with open("D:/project/voice_pathology_ai/voice_data/organics/phrase_sig_dict_50000.pickle","rb") as fr:
    phrase_dict_50000 = pickle.load(fr)

    


# # 데이터 정의
# - 추가적으로 데이터의 크기를 맞춰주기 위해 3초로 padding 및 truncate 실시 https://sequencedata.tistory.com/25 FixAudioLength
# - 논문에서는 400frame으로 설정.(여기서는 500frame)
# - 전처리 방법 결정.
# 

# In[23]:


from torch.utils.data import Dataset, DataLoader

classes = ["healthy","pathology"]
#sr=50000
#win_length =  np.int64(16000/40) # 400
#n_fft= win_length # WINDOWS SIZE중 사용할 길이. WINDOW SIZE가 넘어가면 나머지 것들은 zero padding. 세로 길이
#hop_length= np.int64( np.ceil(win_length/4) ) #  얼마만큼 시간 주기(sample)를 이동하면서 분석을 할 것인지. 일반적으로 window size의 1/4
#또는 10ms만큼으로 한다고 한다.
#hop_length가 mfcc의 frame수를 결정한다.



class svd_dataset(Dataset):
    def __init__(self,data_path_list,classes,data_num,training,mel_params,transform=None,normalize=None):
        #클래스에서 사용할 인자를 받아 인스턴스 변수로 저장하는 일을 한다.
        #예를들면, 이미지의 경로 리스트를 저장하는 일을 하게 된다.
        
        #data_num : k 개 데이터 셋 중 어떤것을 쓸지
        #test인지 아닌지.
        
        self.path_list = data_path_list[data_num]
        self.data_num = data_num
        self.training = training
        self.label = svd_dataset.get_label(self.path_list,training,data_num)
        self.classes = classes
        self.transform = transform
        self.normalize = normalize
        
        # sweep params
        self.mel_params = mel_params
        #sr,n_mfcc,lifter, hop_length , win_length , n_mels , n_fft , f_max , batch_size
        
        
    
    @classmethod
    def get_label(cls,data_path_list,training,data_num):
        label_list=[]
        
        if training:
            for idx,x in enumerate(data_path_list):
                label_list.append(Y_train_list[data_num][idx])
        else:
            for idx,x in enumerate(data_path_list):
                label_list.append(Y_valid_list[data_num][idx])
        #print(label_list)
        return label_list
    
    
    def __len__(self):
        return len(self.path_list)
        #데이터 셋의 길이를 정수로 반환한다.     
    
       
    def __getitem__(self, idx):
        """
        1. path를 받아서, 소리에서 mfcc를 추출
        2. mfcc를 224프레임으로 패딩.
        3. resnet에 사용되기 위해 3채널로 복사(rgb 처럼)
        4. 0~1 정규화
        
        """
        sig=None
        sample_f_max=None
        sample_win_length=None
        
        if self.mel_params["sr"] ==16000:
            sig = phrase_dict_16000[self.path_list[idx]]  
            
        elif self.mel_params["sr"] ==32000:
            sig = phrase_dict_32000[self.path_list[idx]]
            
        else:
            sig = phrase_dict_50000[self.path_list[idx]]
            
        
        length = self.mel_params["sr"]*2 #sample rate *2 padding을 위한 파라미터 (하이퍼 파라미터로인해 사이즈는 계속 바뀐다.)
        pad1d = lambda a, i: a[0:i] if a.shape[0] > i else np.hstack((a, np.zeros((i-a.shape[0]))))        
        sig = pad1d(sig,length)        
        
        ###signal norm
        sig = (sig-sig.mean())/sig.std()
        ###
        sig=torch.tensor(sig, dtype=torch.float32)
        
        #f-max 조절
        if self.mel_params["f_max"] >self.mel_params["sr"]/2:
            sample_f_max = self.mel_params["sr"]/2
            
        #win_size 조절
        if self.mel_params["win_length"] >self.mel_params["n_fft"]:
            sample_win_length=self.mel_params["n_fft"]
        

        
        MFCC = T.MFCC(
                        sample_rate = self.mel_params["sr"],
                        n_mfcc = self.mel_params["n_mfcc"],
                        melkwargs={
                          'n_fft': self.mel_params["n_fft"],
                          'n_mels': self.mel_params["n_mels"],
                          'hop_length': self.mel_params["hop_length"],
                          'mel_scale': self.mel_params["mel_scale"],
                            'win_length' : sample_win_length,
                            
                        }
                    )
        
        MFCCs=MFCC(sig)
        
        #MFCCs = librosa.feature.mfcc(y=sig,sr=self.mel_params["sr"],
        #                                n_mfcc=self.mel_params["n_mfcc"],
        #                                dct_type=self.mel_params["dct_type"], # type2 default
        #                                lifter =self.mel_params["lifter"],
        #                                #mel spectro
        #                                n_mels = self.mel_params["n_mels"],
        #                                hop_length = self.mel_params["hop_length"],
        #                                n_fft = self.mel_params["n_fft"],
        #                                win_length = sample_win_length,
        #                                fmax = sample_f_max,)
        MFCCs = MFCCs[1:,]
        #MFCCs=(MFCCs-self.mfcc_normalize[0])/self.mfcc_normalize[1]
        (nframes, ncoeff) = MFCCs.shape
        cep_lifter = self.mel_params["lifter"]
        
        if cep_lifter > 0:
            n = np.arange(ncoeff)
            lift = 1 + (cep_lifter / 2) * np.sin(np.pi * n / cep_lifter)
            MFCCs *= lift        
        
        if self.transform:
            MFCCs=MFCCs.type(torch.float32)# 타입 변화
            MFCCs=MFCCs.squeeze().mean(axis=1)
            
            # global normalize
            if self.normalize:
                MFCCs=self.normalize(MFCCs)            
        else:
            pass
            #print("else")
            mel_feature = torch.from_numpy(mel_feature).type(torch.float32)
            mel_feature=mel_feature.unsqueeze(0)#cnn 사용위해서 추가
            #MFCCs = MFCCs.permute(2, 0, 1)
        return MFCCs, self.classes.index(self.label[idx])
    


# In[24]:



# test set 제작을 위한 class
class svd_test_set(Dataset):
    def __init__(self,data_path_list,classes,mel_params,transform=None,normalize=None):
        #클래스에서 사용할 인자를 받아 인스턴스 변수로 저장하는 일을 한다.
        #예를들면, 이미지의 경로 리스트를 저장하는 일을 하게 된다.
        
        #data_num : k 개 데이터 셋 중 어떤것을 쓸지
        #test인지 아닌지.
        
        self.path_list = data_path_list
        self.label = svd_test_set.get_label(self.path_list)
        self.classes=classes
        self.transform=transform
        self.normalize=normalize
        
        # sweep params
        self.mel_params = mel_params
        #sr,n_mfcc,dct_type,lifter, hop_length , win_length , n_mels , n_fft , f_max , batch_size   
        
    
    @classmethod
    def get_label(cls,data_path_list):
        label_list=[]
        
        for idx,x in enumerate(data_path_list):
            label_list.append(Y_test[idx])
        #print(label_list)
        return label_list
    
    def __len__(self):
        return len(self.path_list)
        #데이터 셋의 길이를 정수로 반환한다. 
        
    def __getitem__(self, idx):
        """
        1. path를 받아서, 소리에서 mfcc를 추출
        2. mfcc를 224프레임으로 패딩.
        3. resnet에 사용되기 위해 3채널로 복사(rgb 처럼)
        4. 0~1 정규화
        
        """
        sig=None
        sample_f_max=None
        sample_win_length=None
        
        if self.mel_params["sr"] ==16000:
            sig = phrase_dict_16000[self.path_list[idx]]            
        elif self.mel_params["sr"] ==32000:
            sig = phrase_dict_32000[self.path_list[idx]]
        else:
            sig = phrase_dict_50000[self.path_list[idx]]
            
        
        length = self.mel_params["sr"]*2 #sample rate *2 padding을 위한 파라미터 (하이퍼 파라미터로인해 사이즈는 계속 바뀐다.)
        pad1d = lambda a, i: a[0:i] if a.shape[0] > i else np.hstack((a, np.zeros((i-a.shape[0]))))        
        sig = pad1d(sig,length)        
        
        ###signal norm
        sig = (sig-sig.mean())/sig.std()
        ###
        sig=torch.tensor(sig,dtype=torch.float32)
        
        #f-max 조절
        if self.mel_params["f_max"] >self.mel_params["sr"]/2:
            sample_f_max = self.mel_params["sr"]/2
            
        #win_size 조절
        if self.mel_params["win_length"] >self.mel_params["n_fft"]:
            sample_win_length=self.mel_params["n_fft"]
        
        
        MFCC = T.MFCC(
                        sample_rate = self.mel_params["sr"],
                        n_mfcc = self.mel_params["n_mfcc"],
                        melkwargs={
                          'n_fft': self.mel_params["n_fft"],
                          'n_mels': self.mel_params["n_mels"],
                          'hop_length': self.mel_params["hop_length"],
                          'mel_scale': self.mel_params["mel_scale"],
                            'win_length' : sample_win_length,
                            
                        }
                    )
        
        MFCCs=MFCC(sig)
        
        #MFCCs = librosa.feature.mfcc(y=sig,sr=self.mel_params["sr"],
        #                                n_mfcc=self.mel_params["n_mfcc"],
        #                                dct_type=self.mel_params["dct_type"], # type2 default
        #                                lifter =self.mel_params["lifter"],
        #                                #mel spectro
        #                                n_mels = self.mel_params["n_mels"],
        #                                hop_length = self.mel_params["hop_length"],
        #                                n_fft = self.mel_params["n_fft"],
        #                                win_length = sample_win_length,
        #                                fmax = sample_f_max,)
        MFCCs = MFCCs[1:,]
        #MFCCs=(MFCCs-self.mfcc_normalize[0])/self.mfcc_normalize[1]
        (nframes, ncoeff) = MFCCs.shape
        cep_lifter = self.mel_params["lifter"]
        
        if cep_lifter > 0:
            n = np.arange(ncoeff)
            lift = 1 + (cep_lifter / 2) * np.sin(np.pi * n / cep_lifter)
            MFCCs *= lift    
        
        if self.transform:
            MFCCs=MFCCs.type(torch.float32)# 타입 변화
            MFCCs=MFCCs.squeeze().mean(axis=1)
            
            # global normalize
            if self.normalize:
                MFCCs=self.normalize(MFCCs)            
        else:
            pass
            #print("else")
            mel_feature = torch.from_numpy(mel_feature).type(torch.float32)
            mel_feature=mel_feature.unsqueeze(0)#cnn 사용위해서 추가
            #MFCCs = MFCCs.permute(2, 0, 1)
        return MFCCs, self.classes.index(self.label[idx])
    
    


# # 데이터 로더

# In[25]:


#3. 하이퍼 파라미터
#BATCH_SIZE =  32 #한 배치당 32개 음성데이터
EPOCHS = 40 # 전체 데이터 셋을 50번 반복
lr=0.0001
augment_kind="no"


# In[26]:


#DATA LOADER 함수가 BATCH_size 단위로 분리해 지정.

#확인을 위해 데이터셋 하나만 확인


train_loader = torch.utils.data.DataLoader(dataset = 
                                           svd_dataset(
                                               X_train_list,
                                               classes,
                                               transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정. to tensor는 -데이터는 노멀라이즈못함.
                                               #normalize=transforms.Normalize((-56.4917, -56.4917,-56.4917), (17.9446,17.9446,17.9446)),
                                               mel_params = dict(
                                                        sr = run_config["sr"],
                                                        n_mfcc=run_config["n_mfcc"],
                                                        lifter=run_config["lifter"],
                                                       
                                                        n_mels = run_config["n_mels"],
                                                        n_fft = run_config["n_fft"],
                                                        win_length = run_config["win_length"],
                                                        hop_length = run_config["hop_length"],
                                                        f_max = run_config["f_max"],
                                                        mel_scale = run_config["mel_scale"]
                                               ),
                                               data_num=run_config["fold"],
                                               training=True
                                           ),
                                           batch_size = run_config["batch_size"],
                                           shuffle = True,
                                           ) # 순서가 암기되는것을 막기위해.

validation_loader = torch.utils.data.DataLoader(dataset = 
                                           svd_dataset(
                                               X_valid_list,
                                               classes,
                                               transform = transforms.ToTensor(),
                                               mel_params = dict(
                                                        sr = run_config["sr"],
                                                        n_mfcc=run_config["n_mfcc"],
                                                        lifter=run_config["lifter"],
                                                       
                                                        n_mels = run_config["n_mels"],
                                                        n_fft = run_config["n_fft"],
                                                        win_length = run_config["win_length"],
                                                        hop_length = run_config["hop_length"],
                                                        f_max = run_config["f_max"],
                                                   mel_scale = run_config["mel_scale"]
                                               ),                      
                                               #normalize=transforms.Normalize((-56.4917, -56.4917,-56.4917), (17.9446,17.9446,17.9446)),                                               
                                               data_num=run_config["fold"],
                                               training=False
                                           ),
                                           batch_size = run_config["batch_size"],
                                           shuffle = True,)


# In[27]:


# 테스트 데이터 로더.

test_loader = torch.utils.data.DataLoader(dataset = 
                                               svd_test_set(
                                                   X_test,
                                                   classes,
                                                   mel_params = dict(
                                                        sr = run_config["sr"],
                                                        n_mfcc=run_config["n_mfcc"],
                                                        dct_type=run_config["dct_type"],
                                                        lifter=run_config["lifter"],
                                                       
                                                        n_mels = run_config["n_mels"],
                                                        n_fft = run_config["n_fft"],
                                                        win_length = run_config["win_length"],
                                                        hop_length = run_config["hop_length"],
                                                        f_max = run_config["f_max"],
                                                       mel_scale = run_config["mel_scale"],
                                               ),                                            
                                                   #normalize=transforms.Normalize((-56.4917, -56.4917,-56.4917), (17.9446,17.9446,17.9446)),                                                   
                                                   transform = transforms.ToTensor(),
                                               ),
                                               batch_size = run_config["batch_size"],
                                               shuffle = True,) 


# # 데이터 확인

# In[28]:



sr=50000
win_length =  run_config["win_length"] # 400
n_fft= run_config["n_fft"] # WINDOWS SIZE중 사용할 길이. WINDOW SIZE가 넘어가면 나머지 것들은 zero padding. 세로 길이
hop_length=run_config["hop_length"] #  얼마만큼 시간 주기(sample)를 이동하면서 분석을 할 것인지. 일반적으로 window size의 1/4
#또는 10ms만큼으로 한다고 한다.
#hop_length가 mfcc의 frame수를 결정한다.


# In[29]:


# 4. 데이터 확인하기
for (X_train,Y_train) in train_loader:
    print("X_train : ",X_train.size(),'type:',X_train.type())
    print("Y_train : ",Y_train.size(),'type:',Y_train.type())
    break
    
print(Y_train[0])
print(X_train[0])
#batch: 32 / 3채널 / frame수: 500  /  feature수: 13


# In[30]:


#valiation set 확인
for (X_valid,Y_valid) in validation_loader:
    print("X_valid : ",X_valid.size(),'type:',X_valid.type())
    print("Y_valid : ",Y_valid.size(),'type:',Y_valid.type())
    break

print(Y_valid[0])
print(X_valid[0])

#batch: 32 / 3채널 / frame수: 500  /  feature수: 13


# In[31]:


#valiation set 확인
for (test_data,test_label) in validation_loader:
    print("X_test : ",test_data.size(),'type:',test_data.type())
    print("Y_test : ",test_label.size(),'type:',test_label.type())
    break

print(test_label[0])
print(test_data[0])

#batch: 32 / 3채널 / frame수: 500  /  feature수: 13


# # RESNET

# In[32]:


# 모델 
# pretrained

class MfccDense(nn.Module):
    def __init__(self,in_dim):
        super(MfccDense, self).__init__()
        self.in_dim = in_dim
        self.fc = nn.Sequential(
            nn.Linear(in_dim, 128),
            nn.ReLU(),
            nn.Linear(128, 128),
            nn.BatchNorm1d(128),
            nn.ReLU(),
            nn.Linear(128, 2),
        )

    def forward(self, x):
        logits = self.fc(x)
        return logits    




def model_initialize(n_mfcc):
    model = MfccDense( in_dim=n_mfcc ).cuda()
    return model
model=model_initialize(run_config['n_mfcc'])


# In[33]:


criterion = nn.CrossEntropyLoss()
optimizer = torch.optim.Adam(model.parameters(),lr=lr)
print(model)


# In[21]:


# get the model summary
from torchsummary import summary
#summary(model, input_size=(3, 128, 300), device=DEVICE.type)


# In[22]:


#8. 학습
def train(model,train_loader,optimizer, log_interval):
    model.train()    
    correct = 0
    train_loss = 0
    for batch_idx,(image,label) in enumerate(train_loader):
        image = image.to(DEVICE)
        label = label.to(DEVICE)
        #데이터들 장비에 할당
        optimizer.zero_grad() # device 에 저장된 gradient 제거
        output = model(image) # model로 output을 계산
        loss = criterion(output, label) #loss 계산
        train_loss += loss.item()
        prediction = output.max(1,keepdim=True)[1] # 가장 확률이 높은 class 1개를 가져온다.그리고 인덱스만
        correct += prediction.eq(label.view_as(prediction)).sum().item()# 아웃풋이 배치 사이즈 32개라서.
        loss.backward() # loss 값을 이용해 gradient를 계산
        optimizer.step() # Gradient 값을 이용해 파라미터 업데이트.
    train_loss/=len(train_loader.dataset)
    train_accuracy = 100. * correct / len(train_loader.dataset)
    return train_loss,train_accuracy


# In[23]:


#9. 학습 진행하며, validation 데이터로 모델 성능확인
def evaluate(model,valid_loader):
    model.eval()
    valid_loss = 0
    correct = 0
    #no_grad : 그래디언트 값 계산 막기.
    with torch.no_grad():
        for image, label in valid_loader:
            image = image.to(DEVICE)
            label = label.to(DEVICE)
            output = model(image)
            valid_loss += criterion(output, label).item()
            prediction = output.max(1,keepdim=True)[1] # 가장 확률이 높은 class 1개를 가져온다.그리고 인덱스만
            correct += prediction.eq(label.view_as(prediction)).sum().item()# 아웃풋이 배치 사이즈 32개라서.
            #true.false값을 sum해줌. item
        valid_loss /= len(valid_loader.dataset)
        valid_accuracy = 100. * correct / len(valid_loader.dataset)
        return valid_loss,valid_accuracy


# In[24]:


#데이터 로더 제작 함수

def load_data(data_ind):

    train_loader = torch.utils.data.DataLoader(dataset = 
                                               svd_dataset(
                                                   X_train_list,
                                                   classes,
                                                   transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정. to tensor는 -데이터는 노멀라이즈못함.
                                                   #normalize=transforms.Normalize((-56.4917, -56.4917,-56.4917), (17.9446,17.9446,17.9446)),
                                                   mel_params = dict(
                                                        sr = wandb.config.sr,
                                                        n_mfcc=wandb.config.n_mfcc,
                                                        lifter=wandb.config.lifter,
                                                        n_mels = wandb.config.n_mels,
                                                        n_fft = wandb.config.n_fft,
                                                        win_length = wandb.config.win_length,
                                                        hop_length = wandb.config.hop_length,
                                                        f_max = wandb.config.f_max,
                                                        mel_scale = wandb.config.mel_scale
                                                   ),
                                                   data_num=data_ind,
                                                   training=True
                                               ),
                                               batch_size = wandb.config.batch_size,
                                               shuffle = True,
                                               ) # 순서가 암기되는것을 막기위해.

    validation_loader = torch.utils.data.DataLoader(dataset = 
                                               svd_dataset(
                                                   X_valid_list,
                                                   classes,
                                                   transform = transforms.ToTensor(),
                                                   mel_params = dict(
                                                        sr = wandb.config.sr,
                                                        n_mfcc=wandb.config.n_mfcc,
                                                        lifter=wandb.config.lifter,
                                                        n_mels = wandb.config.n_mels,
                                                        n_fft = wandb.config.n_fft,
                                                        win_length = wandb.config.win_length,
                                                        hop_length = wandb.config.hop_length,
                                                        f_max = wandb.config.f_max,
                                                       mel_scale = wandb.config.mel_scale
                                                   ),                      
                                                   #normalize=transforms.Normalize((-56.4917, -56.4917,-56.4917), (17.9446,17.9446,17.9446)),                                               
                                                   data_num=data_ind,
                                                   training=False
                                               ),
                                               batch_size = wandb.config.batch_size,
                                               shuffle = True,) 

    return train_loader,validation_loader


# In[26]:


#10. 학습 및 평가.
# resnet34 pretrained true
# kfold 적용

train_accs = []
valid_accs = []



def all_train():
    wandb.init(project="SVD-mfcc-hyp", entity="bub3690",config=run_config)
    data_ind = wandb.config.fold
    check_path = '../../checkpoint/checkpoint_melspectro_resnet18_true_ros_'+str(data_ind)+'_organics.pt'
    print(check_path)
    #wandb.run.name = 'n'### 여기 수정 ###
    print("config:", dict(wandb.config))    

    early_stopping = EarlyStopping(patience = 5, verbose = True, path=check_path)
    train_loader,validation_loader = load_data(data_ind-1)

    best_train_acc = 0 # accuracy 기록용
    best_valid_acc = 0
    
    best_train_loss = 0
    best_valid_loss = 0

    model=model_initialize(wandb.config.n_mfcc-1)
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.Adam(model.parameters(),lr=0.0001)


    print("[{} 교차검증] 학습 시작\n ----- ".format(data_ind))
    for Epoch in range(1,EPOCHS+1):
        train_loss,train_accuracy=train(model,train_loader,optimizer,log_interval=31)
        valid_loss,valid_accuracy = evaluate(model, validation_loader)

        print("\n[EPOCH:{}]\t Train Loss:{:.4f}\t Train Acc:{:.2f} %  | \tValid Loss:{:.4f} \tValid Acc: {:.2f} %\n".
              format(Epoch,train_loss,train_accuracy,valid_loss,valid_accuracy))
        #wandb.log({"metric": run.config.param1, "epoch": epoch})
            
        early_stopping(valid_loss, model)
        if -early_stopping.best_score == valid_loss:
            best_train_acc, best_valid_acc = train_accuracy,valid_accuracy
            best_train_loss, best_valid_loss = train_loss,valid_loss
            
            wandb.log({"Valid/Loss": best_valid_loss, 
                       "Valid/Accuracy": best_valid_acc,
                      }, step=Epoch)
            #wandb.run.summary.update({"best_valid_{}fold_acc".format(data_ind) : best_valid_acc})
        else:
            # 이전 최고 기록을 log
            wandb.log({"Valid/Loss": best_valid_loss, 
                       "Valid/Accuracy": best_valid_acc,
                      }, step=Epoch)

        if early_stopping.early_stop:
                train_accs.append(best_train_acc)
                valid_accs.append(best_valid_acc)
                print("[{} 교차검증] Early stopping".format(data_ind))
                break

        if Epoch==EPOCHS:
            #만약 early stop 없이 40 epoch라서 중지 된 경우.
            train_accs.append(best_train_acc)
            valid_accs.append(best_valid_acc)


# In[ ]:




if __name__ == '__main__':
    wandb.agent(sweep_id, function=all_train,count=500)
