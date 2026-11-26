#include "KufAvatar.h"

#include "AssetRegistry/AssetRegistryModule.h"
#include "Animation/AnimSequence.h"
#include "Camera/CameraComponent.h"
#include "Components/SkeletalMeshComponent.h"
#include "Engine/Engine.h"
#include "Engine/World.h"
#include "GameFramework/PlayerController.h"
#include "GameFramework/SpringArmComponent.h"
#include "InputCoreTypes.h"
#include "UnrealClient.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"

AKufAvatar::AKufAvatar()
{
	PrimaryActorTick.bCanEverTick = true;
	USceneComponent* Root = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
	SetRootComponent(Root);
	Mesh = CreateDefaultSubobject<USkeletalMeshComponent>(TEXT("Mesh"));
	Mesh->SetupAttachment(Root);
	Mesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	Boom = CreateDefaultSubobject<USpringArmComponent>(TEXT("Boom"));
	Boom->SetupAttachment(Root);
	Boom->bUsePawnControlRotation = false;
	Boom->bDoCollisionTest = false;
	Boom->TargetArmLength = Dist;
	Camera = CreateDefaultSubobject<UCameraComponent>(TEXT("Camera"));
	Camera->SetupAttachment(Boom);
	Camera->PostProcessSettings.bOverride_MotionBlurAmount = true;
	Camera->PostProcessSettings.MotionBlurAmount = 0.f;
}

void AKufAvatar::BeginPlay()
{
	Super::BeginPlay();
	bSelfTest = FParse::Param(FCommandLine::Get(), TEXT("KufAvatarSelfTest"));
	USkeletalMesh* Sk = LoadObject<USkeletalMesh>(nullptr, *FString::Printf(TEXT("%s/%s.%s"), *MeshFolder, *MeshName, *MeshName));
	if (Sk)
	{
		Mesh->SetSkeletalMesh(Sk);
	}
	FAssetRegistryModule& Reg = FModuleManager::LoadModuleChecked<FAssetRegistryModule>("AssetRegistry");
	TArray<FAssetData> Found;
	Reg.Get().ScanPathsSynchronous({ MeshFolder }, true);
	Reg.Get().GetAssetsByPath(FName(*MeshFolder), Found, false);
	Found.Sort([](const FAssetData& A, const FAssetData& B) { return A.AssetName.ToString() < B.AssetName.ToString(); });
	for (const FAssetData& A : Found)
	{
		if (A.AssetClassPath == UAnimSequence::StaticClass()->GetClassPathName())
		{
			if (UAnimSequence* S = Cast<UAnimSequence>(A.GetAsset()))
			{
				Anims.Add(S);
			}
		}
	}
	UE_LOG(LogTemp, Display, TEXT("KUF_AVATAR: mesh=%s loaded=%d animations=%d"), *MeshName, Sk != nullptr, Anims.Num());
	if (APlayerController* PC = Cast<APlayerController>(GetController()))
	{
		PC->bShowMouseCursor = false;
		PC->SetInputMode(FInputModeGameOnly());
	}
	Mesh->SetRelativeRotation(FRotator(0.f, MeshYawOffset, 0.f));
	Mesh->SetRelativeScale3D(FVector(MeshScale));         // glTF import is meters->cm (x100); the game's units are already cm
	PlayIndex(0);
}

void AKufAvatar::PlayIndex(int32 Index)
{
	if (Anims.Num() == 0)
	{
		return;
	}
	Current = (Index % Anims.Num() + Anims.Num()) % Anims.Num();
	Mesh->SetAnimationMode(EAnimationMode::AnimationSingleNode);
	Mesh->PlayAnimation(Anims[Current], true);
	const FString Msg = FString::Printf(TEXT("[%d/%d] %s  (%.2fs)   keys: 1-0 Q/E=animation  WASD=move  mouse=look  wheel=zoom  F=turn model 90deg"),
		Current, Anims.Num() - 1, *Anims[Current]->GetName(), Anims[Current]->GetPlayLength());
	if (GEngine)
	{
		GEngine->AddOnScreenDebugMessage(1, 600.f, FColor::Cyan, Msg);
	}
	UE_LOG(LogTemp, Display, TEXT("KUF_AVATAR: playing %s"), *Msg);
}

float AKufAvatar::GroundZ(const FVector& At, bool& bHit) const
{
	FHitResult Hit;
	FCollisionQueryParams P(SCENE_QUERY_STAT(KufAvatarGround), true, this);
	bHit = GetWorld()->LineTraceSingleByChannel(Hit, At + FVector(0, 0, 20000.f), At - FVector(0, 0, 2000000.f), ECC_Visibility, P);
	return bHit ? Hit.ImpactPoint.Z : At.Z;
}

void AKufAvatar::Tick(float DeltaTime)
{
	Super::Tick(DeltaTime);
	APlayerController* PC = Cast<APlayerController>(GetController());
	if (PC)
	{
		float DX = 0.f, DY = 0.f;
		PC->GetInputMouseDelta(DX, DY);
		CamYaw += DX * 0.25f;
		CamPitch = FMath::Clamp(CamPitch + DY * 0.25f, -80.f, 10.f);
		float Wheel = 0.f;
		if (PC->WasInputKeyJustPressed(EKeys::MouseScrollUp)) Wheel -= 60.f;
		if (PC->WasInputKeyJustPressed(EKeys::MouseScrollDown)) Wheel += 60.f;
		Dist = FMath::Clamp(Dist + Wheel, 120.f, 3000.f);
		Boom->TargetArmLength = Dist;
		const FKey Num[10] = { EKeys::One, EKeys::Two, EKeys::Three, EKeys::Four, EKeys::Five, EKeys::Six, EKeys::Seven, EKeys::Eight, EKeys::Nine, EKeys::Zero };
		for (int32 i = 0; i < 10; ++i)
		{
			if (PC->WasInputKeyJustPressed(Num[i])) PlayIndex(i);
		}
		if (PC->WasInputKeyJustPressed(EKeys::E)) PlayIndex(Current + 1);
		if (PC->WasInputKeyJustPressed(EKeys::Q)) PlayIndex(Current - 1);
		if (PC->WasInputKeyJustPressed(EKeys::F))
		{
			MeshYawOffset += 90.f;
			Mesh->SetRelativeRotation(FRotator(0.f, MeshYawOffset, 0.f));
		}
		FVector Move = FVector::ZeroVector;
		const FRotator Yaw(0.f, CamYaw, 0.f);
		const FVector Fwd = FRotationMatrix(Yaw).GetUnitAxis(EAxis::X), Right = FRotationMatrix(Yaw).GetUnitAxis(EAxis::Y);
		if (PC->IsInputKeyDown(EKeys::W)) Move += Fwd;
		if (PC->IsInputKeyDown(EKeys::S)) Move -= Fwd;
		if (PC->IsInputKeyDown(EKeys::D)) Move += Right;
		if (PC->IsInputKeyDown(EKeys::A)) Move -= Right;
		if (!Move.IsNearlyZero())
		{
			Move.Normalize();
			const float Speed = MoveSpeed * (PC->IsInputKeyDown(EKeys::LeftShift) ? 2.5f : 1.f);
			AddActorWorldOffset(Move * Speed * DeltaTime);
			Mesh->SetWorldRotation(FRotator(0.f, Move.Rotation().Yaw + MeshYawOffset, 0.f));
		}
	}
	bool bHit = false;
	const FVector Loc = GetActorLocation();
	const float Z = GroundZ(Loc, bHit);
	if (bHit)
	{
		SetActorLocation(FVector(Loc.X, Loc.Y, FMath::FInterpTo(Loc.Z, Z, DeltaTime, 20.f)));
		bHaveGround = true;
	}
	Boom->SetWorldRotation(FRotator(CamPitch, CamYaw, 0.f));
	Boom->SetWorldLocation(GetActorLocation() + FVector(0, 0, 120.f));
	if (FParse::Param(FCommandLine::Get(), TEXT("KufAvatarShots")))
	{
		// headless camera: no human at the keyboard; step through animations / camera angles and take screenshots
		SelfTestTime += DeltaTime;
		const int32 Step = (int32)(SelfTestTime / 2.5f);
		if (Step != ShotStep)
		{
			ShotStep = Step;
			if (Step >= 1 && Step <= 6)
			{
				const int32 Anim[7] = { 0, 0, 3, 6, 9, 12, 15 };
				PlayIndex(Anim[Step]);
				CamYaw = (Step % 3) * 40.f;
				CamPitch = (Step % 2) ? -15.f : -35.f;
				Dist = (Step <= 3) ? 350.f : 700.f;
				Boom->TargetArmLength = Dist;
			}
			if (Step >= 1 && Step <= 6)
			{
				FScreenshotRequest::RequestScreenshot(FString::Printf(TEXT("C:/Users/Trey/Desktop/kuf-crusader-data/rig/shots/avatar_%d.png"), Step), false, false);
			}
			UE_LOG(LogTemp, Display, TEXT("KUF_AVATAR_SHOT step=%d anim=%d loc=%s mesh_bounds=%s"), Step, Current, *GetActorLocation().ToString(), *Mesh->Bounds.BoxExtent.ToString());
			if (Step >= 8)
			{
				FPlatformMisc::RequestExit(false);
			}
		}
	}
	if (bSelfTest)
	{
		SelfTestTime += DeltaTime;
		if (SelfTestTime > 3.f)
		{
			const bool bOk = Mesh->GetSkeletalMeshAsset() != nullptr && Anims.Num() > 0;
			UE_LOG(LogTemp, Display, TEXT("KUF_AVATAR_SELFTEST: mesh=%d anims=%d ground=%d at %s RESULT=%s"), Mesh->GetSkeletalMeshAsset() != nullptr, Anims.Num(), bHaveGround, *GetActorLocation().ToString(), bOk ? TEXT("OK") : TEXT("FAIL"));
			FPlatformMisc::RequestExit(false);
		}
	}
}

AKufAvatarGameMode::AKufAvatarGameMode()
{
	DefaultPawnClass = AKufAvatar::StaticClass();
}
